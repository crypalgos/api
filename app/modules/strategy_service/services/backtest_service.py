import logging
from datetime import datetime
from typing import Optional

from app.exceptions.exceptions import ResourceNotFoundException
from app.modules.strategy_service.models.backtest_model import Backtest
from app.modules.strategy_service.repositories.backtest_repository import BacktestRepository
from app.modules.strategy_service.repositories.strategy_repository import StrategyRepository
from app.modules.strategy_service.schema.strategy_schema import (
    BacktestResponseSchema,
    PaginatedBacktestsResponseSchema,
)

logger = logging.getLogger(__name__)

class BacktestService:
    def __init__(
        self,
        strategy_repository: StrategyRepository,
        backtest_repository: BacktestRepository
    ):
        self.strategy_repository = strategy_repository
        self.backtest_repository = backtest_repository

    async def trigger_backtest(
        self,
        user_id: str,
        strategy_id: str,
        start_date: datetime,
        end_date: datetime,
        initial_capital: float,
        leverage: int,
    ) -> tuple[int, dict]:
        """Submit a single backtest job to the Celery worker."""
        from app.modules.strategy_service.tasks import run_asynchronous_backtest_task

        strategy = await self.strategy_repository.get_by_user_and_id(user_id, strategy_id)
        if not strategy:
            raise ResourceNotFoundException("Strategy not found")
            
        # Determine exchange/symbol from canvas JSON (just for the model record)
        datasources = []
        if strategy.canvas_json:
            for node in strategy.canvas_json.get("nodes", []):
                if node.get("type") == "dataNode":
                    datasources.append(node.get("data", {}))
        
        target_symbol = "BTCUSD"
        target_exchange = "delta"
        if datasources:
            target_symbol = datasources[0].get("symbol", target_symbol)
            target_exchange = datasources[0].get("source", target_exchange)

        run = Backtest(
            strategy_id=strategy_id,
            start_date=start_date,
            end_date=end_date,
            initial_capital=initial_capital,
            status="PENDING",
            metrics_json={},
            charting_json={}
        )
        created_run = await self.backtest_repository.create(run)

        task = run_asynchronous_backtest_task.delay(
            backtest_id=created_run.id,
            strategy_id=strategy_id,
            start_date_iso=start_date.isoformat(),
            end_date_iso=end_date.isoformat(),
            initial_capital=initial_capital
        )

        return 202, {
            "backtest_id": created_run.id, 
            "task_id": task.id, 
            "status": "PENDING",
            "message": "Backtest enqueued successfully."
        }

    async def list_backtests(
        self, user_id: str, strategy_id: str, page: int = 1, limit: int = 8
    ) -> tuple[int, PaginatedBacktestsResponseSchema]:
        """Paginated list of historical backtest runs for a strategy."""
        strategy = await self.strategy_repository.get_by_user_and_id(user_id, strategy_id)
        if not strategy:
            raise ResourceNotFoundException("Strategy not found")

        paginated_data = await self.backtest_repository.get_backtests_paginated(
            strategy_id, page, limit
        )

        backtests_schemas = []
        for bt in paginated_data["backtests"]:
            schema = BacktestResponseSchema.model_validate(bt)
            # Strip heavy charting data from paginated list responses
            if isinstance(schema.charting_json, dict):
                if "datasets" in schema.charting_json:
                    schema.charting_json["datasets"] = {}
                if "trades" in schema.charting_json:
                    schema.charting_json["trades"] = {}
                if "correlations" in schema.charting_json:
                    schema.charting_json["correlations"] = {}
                if "monthly" in schema.charting_json:
                    schema.charting_json["monthly"] = {}
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
