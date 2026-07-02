import json
import logging
import os
import shutil
import subprocess
import uuid
from datetime import datetime
from typing import Any

from app.modules.strategy_service.models.strategy_model import Strategy

logger = logging.getLogger(__name__)

def run_in_sandbox(
    strategy: Strategy,
    exchange: str,
    symbol: str,
    start_date: datetime,
    end_date: datetime,
    initial_capital: float,
    leverage: int
) -> dict[str, Any]:
    """
    Executes a backtest in a secure Docker gVisor sandbox.
    Handles data prefetching, volume mounting, and result extraction.
    """
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
    
    # Conditionally fetch options datasets only if options are referenced in the strategy canvas
    has_options = False
    if strategy.canvas_json:
        for node in strategy.canvas_json.get("nodes", []):
            if node.get("type") == "dataNode":
                data = node.get("data", {})
                if data.get("assetClass") == "OPTIONS" or "-" in data.get("symbol", ""):
                    has_options = True
                    break

    if has_options:
        try:
            greeks_list = load_option_greeks_from_clickhouse(exchange.lower(), start_date, end_date)
        except Exception as ge:
            logger.warning(f"Option greeks prefetch failed: {ge}")

        try:
            mark_list = load_option_mark_prices_from_clickhouse(exchange.lower(), start_date, end_date)
        except Exception as me:
            logger.warning(f"Option mark prefetch failed: {me}")
    else:
        logger.info("Skipping option greeks and option mark prices prefetch (no options data nodes in canvas).")

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
            f.write(strategy.compiled_code)

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

from crypalgos_data.exchanges.config import EXCHANGE_REGISTRY
from crypalgos_core.engine.simulator import EngineSimulator
from crypalgos_core.engine.strategy_base import StrategyBase

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

    from crypalgos_core.engine import simulator as sim_mod

    def mock_load_candles(exchange, symbol, start_date, end_date, timeframe="1m"):
        key = f"{exchange.lower()}_{symbol.upper()}_{timeframe.lower()}"
        data = market_data["candles"].get(key, [])
        return np.array(data) if data else np.array([])

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
        exchange_config=EXCHANGE_REGISTRY.get(exchange.lower(), EXCHANGE_REGISTRY['delta'])(),
        initial_capital=initial_capital,
        leverage=leverage,
        slippage_rate=0.0002,
        taker_fee_rate=0.0005
    )

    report = simulator.run(
        strategy_class=strat_class,
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
"""
        with open(os.path.join(sandbox_dir, "sandbox_runner.py"), "w") as f:
            f.write(sandbox_runner_code)

        # 4. Trigger docker execution with network disabled, read-only root, and runsc runtime
        cmd = [
            "docker", "run", "--rm",
            "--runtime=runsc",
            "--network=none",
            "--read-only",
            "--memory=1g",
            "--cpus=1.0",
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
            return report
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
