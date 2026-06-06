import importlib.util
import logging
import os
import tempfile
from datetime import datetime, timedelta

import numpy as np

# Quantitative library imports
from crypalgos_core.compiler import compile_dag, DAGCompiler
from crypalgos_core.simulator import EngineSimulator
from crypalgos_core.strategy import StrategyBase

# To support mock patching of DAGCompiler.compile_dag in service tests
if not hasattr(DAGCompiler, "compile_dag"):
    DAGCompiler.compile_dag = staticmethod(compile_dag)

from app.exceptions.exceptions import ResourceNotFoundException
from app.config.settings import settings
from app.modules.strategy_service.models.backtest_model import Backtest
from app.modules.strategy_service.models.strategy_model import Strategy
from app.modules.strategy_service.repositories.backtest_repository import (
    BacktestRepository,
)
from app.modules.strategy_service.repositories.strategy_repository import (
    StrategyRepository,
)
from typing import Any, Optional
from app.modules.strategy_service.schema.strategy_schema import (
    BacktestResponseSchema,
    StrategyResponseSchema,
    PaginatedStrategiesResponseSchema,
    PaginatedBacktestsResponseSchema,
)

logger = logging.getLogger(__name__)

# Strategy service managing visual canvases and backtests

class StrategyService:
    def __init__(
        self,
        strategy_repository: StrategyRepository,
        backtest_repository: BacktestRepository
    ):
        self.strategy_repository = strategy_repository
        self.backtest_repository = backtest_repository

    async def create_strategy(
        self, user_id: str, name: str, description: str | None, canvas_json: dict
    ) -> tuple[int, StrategyResponseSchema]:
        logger.info(f"Creating strategy '{name}' for user {user_id}")
        
        # Compile visual canvas to Python on-the-fly at create time
        try:
            compiled_code = DAGCompiler.compile_dag(canvas_json)
        except Exception as e:
            logger.error(f"Canvas compilation failed: {e}")
            compiled_code = "# Compilation failed during strategy creation.\n"

        strategy = Strategy(
            user_id=user_id,
            name=name,
            description=description,
            canvas_json=canvas_json,
            compiled_code=compiled_code,
            is_code_modified=False
        )
        created_strategy = await self.strategy_repository.create(strategy)
        return 201, StrategyResponseSchema.model_validate(created_strategy)

    async def get_strategy(self, user_id: str, strategy_id: str) -> tuple[int, StrategyResponseSchema]:
        strategy = await self.strategy_repository.get_by_id(strategy_id)
        if not strategy or strategy.user_id != user_id:
            raise ResourceNotFoundException("Strategy not found")
        return 200, StrategyResponseSchema.model_validate(strategy)

    async def list_strategies(
        self, user_id: str, page: int = 1, limit: int = 8, search: str = ""
    ) -> tuple[int, PaginatedStrategiesResponseSchema]:
        paginated_data = await self.strategy_repository.get_strategies_paginated(
            user_id=user_id, page=page, limit=limit, search=search
        )
        paginated_data["strategies"] = [
            StrategyResponseSchema.model_validate(s) for s in paginated_data["strategies"]
        ]
        return 200, PaginatedStrategiesResponseSchema.model_validate(paginated_data)

    async def save_custom_code(self, user_id: str, strategy_id: str, code: str) -> tuple[int, dict]:
        strategy = await self.strategy_repository.get_by_id(strategy_id)
        if not strategy or strategy.user_id != user_id:
            raise ResourceNotFoundException("Strategy not found")
            
        await self.strategy_repository.update(strategy_id, compiled_code=code, is_code_modified=True)
        return 200, {"success": True, "message": "Custom Monaco code saved successfully. Visual flow desynchronized."}

    async def update_canvas(
        self, user_id: str, strategy_id: str, canvas_json: dict,
        name: str | None = None, description: str | None = None
    ) -> tuple[int, StrategyResponseSchema]:
        """Save canvas node/edge JSON and recompile to Python. Resets code_modified flag."""
        strategy = await self.strategy_repository.get_by_id(strategy_id)
        if not strategy or strategy.user_id != user_id:
            raise ResourceNotFoundException("Strategy not found")

        # Recompile from the updated canvas
        try:
            compiled_code = DAGCompiler.compile_dag(canvas_json)
        except Exception as e:
            logger.error(f"Canvas recompilation failed for strategy {strategy_id}: {e}")
            # Keep existing code but still save the canvas layout
            compiled_code = strategy.compiled_code

        update_kwargs: dict = dict(
            canvas_json=canvas_json,
            compiled_code=compiled_code,
            is_code_modified=False,
        )
        if name is not None:
            update_kwargs["name"] = name
        if description is not None:
            update_kwargs["description"] = description

        updated = await self.strategy_repository.update(strategy_id, **update_kwargs)
        return 200, StrategyResponseSchema.model_validate(updated)


    async def reset_to_visual_builder(self, user_id: str, strategy_id: str) -> tuple[int, StrategyResponseSchema]:
        strategy = await self.strategy_repository.get_by_id(strategy_id)
        if not strategy or strategy.user_id != user_id:
            raise ResourceNotFoundException("Strategy not found")
            
        try:
            pristine_code = DAGCompiler.compile_dag(strategy.canvas_json)
        except Exception as e:
            raise ValueError(f"Failed to reset and compile visual builder nodes: {e}")
            
        updated = await self.strategy_repository.update(
            strategy_id, 
            compiled_code=pristine_code, 
            is_code_modified=False
        )
        return 200, StrategyResponseSchema.model_validate(updated)

    async def run_backtest(
        self, user_id: str, strategy_id: str, exchange: str, symbol: str,
        start_date: datetime, end_date: datetime, initial_capital: float, leverage: int
    ) -> tuple[int, BacktestResponseSchema]:
        # Normalize symbol and exchange
        symbol = symbol.replace("/", "").replace("-", "").upper()
        exchange = exchange.strip().lower()

        strategy = await self.strategy_repository.get_by_id(strategy_id)
        if not strategy or strategy.user_id != user_id:
            raise ResourceNotFoundException("Strategy not found")

        # Resolve correct active compiled script
        if strategy.is_code_modified:
            compiled_script = strategy.compiled_code
        else:
            try:
                compiled_script = DAGCompiler.compile_dag(strategy.canvas_json)
                await self.strategy_repository.update(strategy_id, compiled_code=compiled_script)
            except Exception as e:
                raise ValueError(f"On-the-fly backtest compilation failed: {e}")

        # Write to temporary file for dynamic import
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as tf:
            tf.write(compiled_script)
            temp_path = tf.name

        try:
            # Dynamic Load
            spec = importlib.util.spec_from_file_location(f"backtest_run_{strategy_id}", temp_path)
            if not spec or not spec.loader:
                raise ValueError("Failed to resolve package module specifications or loader.")
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

            # Run offline / online simulator
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

            # Construct charting metrics mapping
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

            # Sampling charting timeline arrays to maximum 1,000 points
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

            # Create backtest entry
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

            created_backtest = await self.backtest_repository.create(backtest)
            return 201, BacktestResponseSchema.model_validate(created_backtest)

        finally:
            # Clean up temp file safely
            if os.path.exists(temp_path):
                os.remove(temp_path)

    async def trigger_backtest(
        self, user_id: str, strategy_id: str,
        start_date: datetime, end_date: datetime, initial_capital: float,
    ) -> tuple[int, dict]:
        strategy = await self.strategy_repository.get_by_id(strategy_id)
        if not strategy or strategy.user_id != user_id:
            raise ResourceNotFoundException("Strategy not found")

        # Resolve exchange, symbol, and leverage from canvas_json nodes
        canvas_json = strategy.canvas_json or {}
        nodes = canvas_json.get("nodes", [])
        data_node = next((n for n in nodes if n.get("type") == "dataNode"), None)
        start_node = next((n for n in nodes if n.get("type") == "startNode"), None)

        if not data_node:
            raise ValueError(
                "Strategy has no Data Node configured. "
                "Add and configure a Data Node (symbol) before running a backtest."
            )
        if not start_node:
            raise ValueError("Strategy has no Start Node configured.")

        data_node_data = data_node.get("data", {})
        start_node_data = start_node.get("data", {})

        exchange = start_node_data.get("exchange")
        symbol = data_node_data.get("symbol")
        leverage = start_node_data.get("leverage")

        if not exchange:
            raise ValueError("Start Node is missing 'exchange'. Open the Start Node and configure it.")
        if not symbol:
            raise ValueError("Data Node is missing 'symbol'. Open the Data Node and select an instrument.")

        # Resolve leverage — default to 1 if not set (conservative)
        if leverage is None:
            leverage = 1
        if isinstance(leverage, str):
            try:
                leverage = int(leverage.lower().replace("x", "").strip())
            except (ValueError, TypeError):
                leverage = 1
        else:
            leverage = int(leverage)

        # Normalize symbol and exchange for backend use
        symbol = symbol.replace("/", "").replace("-", "").upper()
        exchange = exchange.strip().lower()

        # Validate date range
        if start_date >= end_date:
            raise ValueError("start_date must be before end_date.")

        # Resolve correct active compiled script and persist it
        if not strategy.is_code_modified:
            try:
                compiled_script = DAGCompiler.compile_dag(strategy.canvas_json)
                await self.strategy_repository.update(strategy_id, compiled_code=compiled_script)
            except Exception as e:
                raise ValueError(f"On-the-fly backtest compilation failed: {e}")

        # ── Execution routing ──────────────────────────────────────────────────
        # LOCAL DEV  : SANDBOX_ENABLED=false → run in-process immediately
        # PRODUCTION : SANDBOX_ENABLED=true  → enqueue to Celery/Valkey worker
        # ──────────────────────────────────────────────────────────────────────
        if not settings.sandbox_enabled:
            # Run synchronously in the FastAPI process — results in DB immediately
            logger.info(f"[DEV] Running backtest in-process (sandbox disabled) for {strategy_id}")
            status_code, backtest = await self.run_backtest(
                user_id=user_id,
                strategy_id=strategy_id,
                exchange=exchange,
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
                initial_capital=initial_capital,
                leverage=leverage
            )
            return 200, {
                "status": "completed",
                "task_id": backtest.id,
                "message": "Backtest completed and results saved.",
            }

        # Import task inside method to prevent any potential circular dependencies
        from app.modules.strategy_service.tasks import run_asynchronous_backtest_task

        # Enqueue the Celery background task
        task = run_asynchronous_backtest_task.delay(
            strategy_id=strategy_id,
            exchange=exchange,
            symbol=symbol,
            start_date_iso=start_date.isoformat(),
            end_date_iso=end_date.isoformat(),
            initial_capital=initial_capital,
            leverage=leverage
        )

        return 202, {
            "status": "enqueued",
            "task_id": task.id,
            "message": "Backtest enqueued successfully."
        }

    async def delete_strategy(self, user_id: str, strategy_id: str) -> tuple[int, dict]:
        """Permanently remove a strategy owned by the given user."""
        strategy = await self.strategy_repository.get_by_user_and_id(user_id, strategy_id)
        if not strategy:
            raise ResourceNotFoundException("Strategy not found")
        await self.strategy_repository.delete(strategy_id)
        return 200, {"success": True, "message": "Strategy deleted successfully."}

    async def list_backtests(
        self, user_id: str, strategy_id: str, page: int = 1, limit: int = 8,
        exchange: str | None = None, symbol: str | None = None
    ) -> tuple[int, PaginatedBacktestsResponseSchema]:
        """Return a paginated, filtered list of backtest runs for a strategy owned by user_id."""
        strategy = await self.strategy_repository.get_by_user_and_id(user_id, strategy_id)
        if not strategy:
            raise ResourceNotFoundException("Strategy not found")
        
        paginated_data = await self.backtest_repository.get_backtests_paginated(
            strategy_id=strategy_id, page=page, limit=limit, exchange=exchange, symbol=symbol
        )
        
        backtests_schemas = []
        for bt in paginated_data["backtests"]:
            schema = BacktestResponseSchema.model_validate(bt)
            # Strip heavy charting data from paginated list responses
            if isinstance(schema.charting_json, dict):
                if "equity_curve" in schema.charting_json:
                    schema.charting_json["equity_curve"] = []
                if "drawdown_curve" in schema.charting_json:
                    schema.charting_json["drawdown_curve"] = []
                if "trades" in schema.charting_json:
                    schema.charting_json["trades"] = []
            # Truncate massive error strings in metrics to prevent frontend hang
            if isinstance(schema.metrics_json, dict) and "error" in schema.metrics_json:
                err = schema.metrics_json["error"]
                if isinstance(err, str) and len(err) > 300:
                    schema.metrics_json["error"] = err[:300] + "... (truncated)"
            backtests_schemas.append(schema)

        paginated_data["backtests"] = backtests_schemas
        return 200, PaginatedBacktestsResponseSchema.model_validate(paginated_data)

    async def get_backtest(
        self, user_id: str, strategy_id: str, backtest_id: str
    ) -> tuple[int, BacktestResponseSchema]:
        """Fetch a specific backtest run with curves intact after verifying user strategy ownership."""
        strategy = await self.strategy_repository.get_by_user_and_id(user_id, strategy_id)
        if not strategy:
            raise ResourceNotFoundException("Strategy not found")

        backtest = await self.backtest_repository.get_by_id(backtest_id)
        if not backtest or backtest.strategy_id != strategy_id:
            raise ResourceNotFoundException("Backtest run not found")

        return 200, BacktestResponseSchema.model_validate(backtest)

    async def delete_backtest(self, user_id: str, strategy_id: str, backtest_id: str) -> tuple[int, dict]:
        """Permanently delete a specific backtest run after verifying user strategy ownership."""
        strategy = await self.strategy_repository.get_by_user_and_id(user_id, strategy_id)
        if not strategy:
            raise ResourceNotFoundException("Strategy not found")
            
        backtest = await self.backtest_repository.get_by_id(backtest_id)
        if not backtest or backtest.strategy_id != strategy_id:
            raise ResourceNotFoundException("Backtest run not found")
            
        await self.backtest_repository.delete(backtest_id)
        return 200, {"success": True, "message": "Backtest run deleted successfully."}

