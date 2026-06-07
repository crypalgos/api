import ast
import asyncio
import importlib.util
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timedelta
from typing import Any

import numpy as np

# Quantitative library imports
from crypalgos_core.simulator import EngineSimulator
from crypalgos_core.strategy import StrategyBase

from app.celery_app import celery_app
from app.config.settings import settings
from app.db.connect_db import AsyncSessionLocal
from app.modules.strategy_service.models.backtest_model import Backtest
from app.modules.strategy_service.models.strategy_model import Strategy

logger = logging.getLogger(__name__)

from celery.signals import worker_process_init

@worker_process_init.connect
def on_worker_init(*args, **kwargs):
    logger.info("Celery child worker process initialized. Disposing database engine pools.")
    try:
        from app.db.connect_db import engine
        engine.sync_engine.dispose()
    except Exception as e:
        logger.error(f"Failed to dispose engine in worker process init: {e}")

# Tasks running in isolated environments for strategy execution

# Static AST safety validator to shield host and containers from untrusted system calls
FORBIDDEN_IMPORTS = {'os', 'sys', 'subprocess', 'shutil', 'importlib', 'requests', 'urllib', 'socket', 'builtins'}
FORBIDDEN_CALLS = {'eval', 'exec', 'open', 'compile', 'getattr', 'setattr', 'delattr', 'globals', 'locals'}

def validate_strategy_ast(code: str) -> bool:
    """Validate strategy python code using AST parser to prevent security escalations."""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        raise ValueError(f"Syntax validation failed: {e}")
        
    for node in ast.walk(tree):
        # Prevent dangerous imports
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split('.')[0] in FORBIDDEN_IMPORTS:
                    raise ValueError(f"Import of '{alias.name}' is strictly forbidden.")
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.split('.')[0] in FORBIDDEN_IMPORTS:
                raise ValueError(f"Import from '{node.module}' is strictly forbidden.")
                
        # Prevent dangerous built-in dynamic execution functions
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_CALLS:
                raise ValueError(f"Calling built-in function '{node.func.id}()' is strictly forbidden.")
                
        # Prevent dunder sandbox escape techniques
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith('__'):
                raise ValueError(f"Access to private attribute '{node.attr}' is strictly forbidden.")
                
    return True

async def _execute_backtest_internal(
    strategy_id: str, exchange: str, symbol: str,
    start_date: datetime, end_date: datetime, initial_capital: float, leverage: int
) -> dict[str, Any]:
    # Normalize inputs
    symbol = symbol.replace("/", "").replace("-", "").upper()
    exchange = exchange.strip().lower()
    logger.info(f"Asynchronous Celery backtest started for strategy {strategy_id}")

    async with AsyncSessionLocal() as session:
        async with session.begin():
            # 1. Fetch strategy from database
            strategy = await session.get(Strategy, strategy_id)
            if not strategy:
                raise ValueError(f"Strategy {strategy_id} not found in database.")

            compiled_script = strategy.compiled_code

        # Run Static AST safety checks prior to compilation or run
        validate_strategy_ast(compiled_script)

        # ── Execution mode ─────────────────────────────────────────────────────
        # LOCAL DEV  : SANDBOX_ENABLED=false (default) → in-process execution
        # PRODUCTION : SANDBOX_ENABLED=true            → Docker gVisor sandbox
        # ──────────────────────────────────────────────────────────────────────
        USE_SANDBOX = settings.sandbox_enabled

        if not USE_SANDBOX:
            # ── In-process execution (local dev / testing) ─────────────────────
            logger.info(f"[DEV] Running backtest in-process for strategy {strategy_id}")

            with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as tf:
                tf.write(compiled_script)
                temp_path = tf.name

            try:
                spec = importlib.util.spec_from_file_location(f"backtest_run_{strategy_id}", temp_path)
                if not spec or not spec.loader:
                    raise ValueError("Failed to resolve module spec/loader.")
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                strat_class = None
                for name in dir(module):
                    obj = getattr(module, name)
                    if isinstance(obj, type) and issubclass(obj, StrategyBase) and obj is not StrategyBase:
                        strat_class = obj
                        break

                if not strat_class:
                    raise ValueError("No compiled StrategyBase subclass found in strategy script.")

                simulator = EngineSimulator(
                    initial_capital=initial_capital,
                    leverage=leverage,
                    slippage_rate=0.0002,
                    maker_fee_rate=0.0002,
                    taker_fee_rate=0.0004
                )
                report = simulator.run(
                    strategy_class=strat_class,
                    exchange=exchange.lower(),
                    symbol=symbol.upper(),
                    start_date=start_date,
                    end_date=end_date
                )
            finally:
                if os.path.exists(temp_path):
                    os.remove(temp_path)

        else:
            # =========================================================================
            # Production/Staging Secure Docker gVisor Sandbox Execution
            # =========================================================================
            # 1. Resolve all required datasources from visual Canvas JSON configuration
            datasources = []
            if strategy.canvas_json:
                for node in strategy.canvas_json.get("nodes", []):
                    if node.get("type") == "dataNode":
                        data = node.get("data", {})
                        ds_sym = data.get("symbol", "BTCUSD").replace("/", "").upper()
                        if ds_sym.endswith("USDT"):
                            ds_sym = ds_sym[:-1]
                        datasources.append({
                            "symbol": ds_sym,
                            "exchange": data.get("source", "delta").lower(),
                            "timeframe": data.get("timeframe", "1m")
                        })
            
            if not datasources:
                datasources = [{
                    "symbol": symbol.upper(),
                    "exchange": exchange.lower(),
                    "timeframe": "1m"
                }]

            # 2. Prefetch all required market data on host using secure database connection
            from crypalgos_core.database import (
                load_candles_from_clickhouse,
                load_funding_rates_from_clickhouse,
                load_option_greeks_from_clickhouse,
                load_option_mark_prices_from_clickhouse,
            )

            candles_dict = {}
            funding_dict = {}
            for ds in datasources:
                ds_sym = ds["symbol"]
                ds_exch = ds["exchange"]
                ds_tf = ds["timeframe"]

                # Fetch candles - let exceptions propagate directly (no fallback)
                candles_np = load_candles_from_clickhouse(
                    exchange=ds_exch,
                    symbol=ds_sym,
                    start_date=start_date,
                    end_date=end_date,
                    timeframe=ds_tf
                )
                if candles_np is None or len(candles_np) == 0:
                    raise ValueError(f"No historical candles found in ClickHouse for {ds_sym} on {ds_exch}")
                
                key = f"{ds_exch.lower()}_{ds_sym.upper()}_{ds_tf.lower()}"
                candles_dict[key] = candles_np.tolist()

                try:
                    funding_list = load_funding_rates_from_clickhouse(
                        exchange=ds_exch,
                        symbol=ds_sym,
                        start_date=start_date,
                        end_date=end_date
                    )
                    funding_dict[ds_sym.upper()] = funding_list
                except Exception as fe:
                    logger.warning(f"Funding prefetch failed for {ds_sym}: {fe}")

            greeks_list = []
            mark_list = []
            try:
                greeks_list = load_option_greeks_from_clickhouse(exchange.lower(), start_date, end_date)
            except Exception as ge:
                logger.warning(f"Option greeks prefetch failed: {ge}")

            try:
                mark_list = load_option_mark_prices_from_clickhouse(exchange.lower(), start_date, end_date)
            except Exception as me:
                logger.warning(f"Option mark prefetch failed: {me}")

            market_data = {
                "candles": candles_dict,
                "funding_rates": funding_dict,
                "option_greeks": greeks_list,
                "option_mark_prices": mark_list
            }

            # 3. Create host mount directory within workspace root for Docker volume isolation
            sandbox_id = str(uuid.uuid4())[:8]
            workspace_root = os.getenv("WORKSPACE_ROOT", "/sandbox_tmp")
            host_workspace_root = os.getenv("HOST_WORKSPACE_ROOT", workspace_root)
            sandbox_image = os.getenv("SANDBOX_IMAGE", "api-api")
            
            sandbox_dir = os.path.join(workspace_root, f"sandbox_tmp_{sandbox_id}")
            host_sandbox_dir = os.path.join(host_workspace_root, f"sandbox_tmp_{sandbox_id}")
            os.makedirs(sandbox_dir, exist_ok=True)
            os.chmod(sandbox_dir, 0o777)

            try:
                # Write strategy python code
                with open(os.path.join(sandbox_dir, "strategy.py"), "w") as f:
                    f.write(compiled_script)

                # Write simulation parameters
                params = {
                    "exchange": exchange.lower(),
                    "symbol": symbol.upper(),
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                    "initial_capital": initial_capital,
                    "leverage": leverage
                }
                with open(os.path.join(sandbox_dir, "params.json"), "w") as f:
                    json.dump(params, f)

                # Write pre-fetched market data
                with open(os.path.join(sandbox_dir, "market_data.json"), "w") as f:
                    json.dump(market_data, f)

                # Write wrapper execution runner
                sandbox_runner_code = """import sys
import os
import json
import importlib.util
import numpy as np
from datetime import datetime
import logging

logging.basicConfig(level=logging.ERROR, force=True)
logging.getLogger("BacktestingEngine.Simulator").setLevel(logging.ERROR)

sys.path.insert(0, "/app")

from crypalgos_core.simulator import EngineSimulator
from crypalgos_core.strategy import StrategyBase

def run():
    with open("/sandbox/params.json", "r") as f:
        params = json.load(f)
    
    exchange = params["exchange"]
    symbol = params["symbol"]
    start_date = datetime.fromisoformat(params["start_date"])
    end_date = datetime.fromisoformat(params["end_date"])
    initial_capital = params["initial_capital"]
    leverage = params["leverage"]

    with open("/sandbox/market_data.json", "r") as f:
        market_data = json.load(f)

    import crypalgos_core.simulator as sim_mod

    def mock_load_candles(exchange, symbol, start_date, end_date, timeframe="1m"):
        key = f"{exchange.lower()}_{symbol.upper()}_{timeframe.lower()}"
        if key not in market_data["candles"]:
            key = symbol.upper()
        raw = market_data["candles"].get(key, [])
        return np.array(raw, dtype=np.float64)

    def mock_load_funding(exchange, symbol, start_date, end_date):
        return market_data["funding_rates"].get(symbol.upper(), [])

    def mock_load_greeks(exchange, start_date, end_date):
        return market_data["option_greeks"]

    def mock_load_option_mark(exchange, start_date, end_date):
        return market_data["option_mark_prices"]

    sim_mod.load_candles_from_clickhouse = mock_load_candles
    sim_mod.load_funding_rates_from_clickhouse = mock_load_funding
    sim_mod.load_option_greeks_from_clickhouse = mock_load_greeks
    sim_mod.load_option_mark_prices_from_clickhouse = mock_load_option_mark

    spec = importlib.util.spec_from_file_location("untrusted_strategy", "/sandbox/strategy.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    strat_class = None
    for name in dir(module):
        obj = getattr(module, name)
        if isinstance(obj, type) and issubclass(obj, StrategyBase) and obj is not StrategyBase:
            strat_class = obj
            break

    if not strat_class:
        raise ValueError("No StrategyBase subclass resolved in strategy script.")

    simulator = EngineSimulator(
        initial_capital=initial_capital,
        leverage=leverage,
        slippage_rate=0.0002,
        maker_fee_rate=0.0002,
        taker_fee_rate=0.0004
    )

    report = simulator.run(
        strategy_class=strat_class,
        exchange=exchange,
        symbol=symbol,
        start_date=start_date,
        end_date=end_date
    )

    with open("/sandbox/result.json", "w") as f:
        json.dump(report, f)

if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        import traceback
        with open("/sandbox/error.json", "w") as f:
            json.dump({"error": str(e), "traceback": traceback.format_exc()}, f)
        sys.exit(1)
"""
                with open(os.path.join(sandbox_dir, "sandbox_runner.py"), "w") as f:
                    f.write(sandbox_runner_code)

                # 4. Trigger isolated unprivileged container execution via Docker
                # Sets memory limit to 512MB, cpus to 1.0, and completely disables networking (--network none)
                cmd = [
                    "docker", "run", "--rm",
                    "--network", "none",
                    "--memory", "512m",
                    "--cpus", "1.0",
                    "-v", f"{host_sandbox_dir}:/sandbox",
                    sandbox_image,
                    "/app/.venv/bin/python", "/sandbox/sandbox_runner.py"
                ]
                
                logger.info(f"Triggering secure strategy sandbox container: {' '.join(cmd)}")
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

                # 5. Extract output report or strategy execution exceptions
                result_path = os.path.join(sandbox_dir, "result.json")
                error_path = os.path.join(sandbox_dir, "error.json")

                if os.path.exists(result_path):
                    with open(result_path, "r") as f:
                        report = json.load(f)
                elif os.path.exists(error_path):
                    with open(error_path, "r") as f:
                        err_info = json.load(f)
                    raise ValueError(f"Sandbox strategy runtime exception: {err_info.get('error')}\n{err_info.get('traceback')}")
                else:
                    stderr_out = res.stderr or ""
                    stdout_out = res.stdout or ""
                    raise ValueError(
                        f"Strategy container aborted. Exit code: {res.returncode}\n"
                        f"Stdout: {stdout_out}\nStderr: {stderr_out}"
                    )
            finally:
                if os.path.exists(sandbox_dir):
                    shutil.rmtree(sandbox_dir)

        # 6. Construct charting metrics mapping
        metrics = {
            "net_profit": report.get("net_profit", 0.0),
            "profit_pct": (report.get("net_profit", 0.0) / initial_capital) * 100.0,
            "total_trades": len(report.get("trades", [])),
            "win_rate": report.get("win_rate", 0.0),
            "profit_factor": report.get("profit_factor", 0.0),
            "sharpe_ratio": report.get("sharpe_ratio", 0.0),
            "max_drawdown": report.get("max_drawdown", 0.0),
            "final_balance": report.get("final_balance", initial_capital)
        }

        raw_equity = report.get("equity_curve", [])
        raw_drawdown = report.get("drawdown_curve", [])
        
        def downsample(timeline: list, target: int = 1000) -> list:
            n = len(timeline)
            if n <= target:
                return timeline
            step = n // target
            return [timeline[i] for i in range(0, n, step)] + [timeline[-1]]

        charting = {
            "trades": report.get("trades", []),
            "equity_curve": downsample(raw_equity),
            "drawdown_curve": downsample(raw_drawdown)
        }

        # 7. Save Backtest Run in database
        backtest = Backtest(
            strategy_id=strategy_id,
            exchange=exchange,
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            initial_capital=initial_capital,
            leverage=leverage,
            metrics_json=metrics,
            charting_json=charting
        )

        async with session.begin():
            session.add(backtest)
            await session.flush()
            await session.refresh(backtest)
            
        logger.info(f"Asynchronous Celery backtest run successfully saved: {backtest.id}")
        return {
            "success": True,
            "backtest_id": backtest.id,
            "metrics": metrics
        }


async def _execute_and_handle_backtest_internal(
    strategy_id: str, exchange: str, symbol: str,
    start_date: datetime, end_date: datetime, initial_capital: float, leverage: int
) -> dict[str, Any]:
    # Dispose of inherited connection descriptors in child process prefork pools
    from app.db.connect_db import engine
    engine.sync_engine.dispose()

    try:
        return await _execute_backtest_internal(
            strategy_id=strategy_id,
            exchange=exchange,
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            initial_capital=initial_capital,
            leverage=leverage
        )
    except Exception as e:
        logger.error(f"Error during backtest execution: {str(e)}")
        err_msg = str(e)
        # Cap error message length to prevent bloating DB with sandbox stderr dumps
        if len(err_msg) > 500:
            err_msg = err_msg[:500] + "... (truncated)"
        is_clickhouse_err = (
            "ClickHouse" in err_msg or 
            "DatabaseError" in err_msg or 
            "Authentication failed" in err_msg or 
            "Connection refused" in err_msg or 
            "load_candles" in err_msg or 
            "candles" in err_msg
        )

        metrics = {
            "error": "Backtesting is currently unavailable. " + (
                "The ClickHouse OLAP database is offline or unauthenticated." 
                if is_clickhouse_err else err_msg
            ),
            "net_profit": 0.0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "sharpe_ratio": 0.0,
            "max_drawdown": 0.0,
            "profit_pct": 0.0,
            "total_trades": 0
        }
        charting = {
            "trades": [],
            "equity_curve": [],
            "drawdown_curve": []
        }

        async with AsyncSessionLocal() as session:
            backtest = Backtest(
                strategy_id=strategy_id,
                exchange=exchange,
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
                initial_capital=initial_capital,
                leverage=leverage,
                metrics_json=metrics,
                charting_json=charting
            )
            async with session.begin():
                session.add(backtest)
                await session.flush()
                await session.refresh(backtest)
            backtest_id = backtest.id

        return {
            "success": False,
            "backtest_id": backtest_id,
            "error": metrics["error"]
        }


@celery_app.task(name="app.modules.strategy_service.tasks.run_asynchronous_backtest_task")
def run_asynchronous_backtest_task(
    strategy_id: str, exchange: str, symbol: str,
    start_date_iso: str, end_date_iso: str, initial_capital: float, leverage: int
) -> dict[str, Any]:
    """Celery background task orchestrating quantitative backtest simulation."""
    start_date = datetime.fromisoformat(start_date_iso)
    end_date = datetime.fromisoformat(end_date_iso)
    return asyncio.run(_execute_and_handle_backtest_internal(
        strategy_id=strategy_id,
        exchange=exchange,
        symbol=symbol,
        start_date=start_date,
        end_date=end_date,
        initial_capital=initial_capital,
        leverage=leverage
    ))
