import logging
from typing import Optional

from app.exceptions.exceptions import ResourceNotFoundException
from app.modules.strategy_service.models.montecarlo_model import MonteCarloRun
from app.modules.strategy_service.repositories.montecarlo_repository import MonteCarloRepository
from app.modules.strategy_service.repositories.backtest_repository import BacktestRepository
from app.modules.strategy_service.repositories.strategy_repository import StrategyRepository
from app.modules.strategy_service.schema.strategy_schema import (
    MonteCarloRunResponseSchema,
    PaginatedMonteCarloRunsResponseSchema,
)

logger = logging.getLogger(__name__)

class MonteCarloService:
    def __init__(
        self,
        strategy_repository: StrategyRepository,
        backtest_repository: BacktestRepository,
        montecarlo_repository: MonteCarloRepository
    ):
        self.strategy_repository = strategy_repository
        self.backtest_repository = backtest_repository
        self.montecarlo_repository = montecarlo_repository

    async def trigger_montecarlo(
        self,
        user_id: str,
        strategy_id: str,
        source_backtest_id: str,
        simulation_count: int,
        method: str,
        random_seed: Optional[int],
    ) -> tuple[int, dict]:
        """Submit a Monte Carlo simulation job consuming an existing backtest result."""
        from app.modules.strategy_service.tasks import run_montecarlo_task

        strategy = await self.strategy_repository.get_by_user_and_id(user_id, strategy_id)
        if not strategy:
            raise ResourceNotFoundException("Strategy not found")

        # Verify the source backtest exists and belongs to this strategy
        source_bt = await self.backtest_repository.get_by_id(source_backtest_id)
        if not source_bt or source_bt.strategy_id != strategy_id:
            raise ResourceNotFoundException("Source backtest not found or does not belong to this strategy")

        run = MonteCarloRun(
            user_id=user_id,
            strategy_id=strategy_id,
            source_backtest_id=source_backtest_id,
            status="PENDING",
            simulation_count=simulation_count,
            method=method,
            random_seed=random_seed,
        )
        created_run = await self.montecarlo_repository.create(run)

        task = run_montecarlo_task.delay(
            run_id=created_run.id,
            strategy_id=strategy_id,
            source_backtest_id=source_backtest_id,
            simulation_count=simulation_count,
            method=method,
            random_seed=random_seed,
        )
        return 202, {"run_id": created_run.id, "task_id": task.id, "status": "PENDING",
                     "message": "Monte Carlo job enqueued successfully."}

    async def get_montecarlo_run(
        self, user_id: str, strategy_id: str, run_id: str
    ) -> tuple[int, MonteCarloRunResponseSchema]:
        """Fetch a specific Monte Carlo run verifying ownership."""
        strategy = await self.strategy_repository.get_by_user_and_id(user_id, strategy_id)
        if not strategy:
            raise ResourceNotFoundException("Strategy not found")

        run = await self.montecarlo_repository.get_by_user_and_run_id(user_id, run_id)
        if not run or run.strategy_id != strategy_id:
            raise ResourceNotFoundException("Monte Carlo run not found")

        return 200, MonteCarloRunResponseSchema.model_validate(run)

    async def list_montecarlo_runs(
        self, user_id: str, strategy_id: str, page: int = 1, limit: int = 8
    ) -> tuple[int, PaginatedMonteCarloRunsResponseSchema]:
        """Paginated list of Monte Carlo runs for a strategy."""
        strategy = await self.strategy_repository.get_by_user_and_id(user_id, strategy_id)
        if not strategy:
            raise ResourceNotFoundException("Strategy not found")

        data = await self.montecarlo_repository.get_runs_paginated(strategy_id, user_id, page, limit)
        return 200, PaginatedMonteCarloRunsResponseSchema.model_validate(data)
