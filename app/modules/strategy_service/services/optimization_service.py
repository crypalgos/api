import logging
from datetime import datetime
from typing import Optional

from app.exceptions.exceptions import ResourceNotFoundException
from app.modules.strategy_service.models.optimization_model import OptimizationRun
from app.modules.strategy_service.repositories.optimization_repository import OptimizationRepository
from app.modules.strategy_service.repositories.strategy_repository import StrategyRepository
from app.modules.strategy_service.schema.strategy_schema import (
    OptimizationRunResponseSchema,
    PaginatedOptimizationRunsResponseSchema,
)

logger = logging.getLogger(__name__)

class OptimizationService:
    def __init__(
        self,
        strategy_repository: StrategyRepository,
        optimization_repository: OptimizationRepository
    ):
        self.strategy_repository = strategy_repository
        self.optimization_repository = optimization_repository

    async def trigger_optimization(
        self,
        user_id: str,
        strategy_id: str,
        start_date: datetime,
        end_date: datetime,
        parameter_space: list,
        objective: str,
        search_type: str,
        max_runs: int,
        constraints: Optional[list],
        initial_capital: float,
    ) -> tuple[int, dict]:
        """Submit a parameter optimization job and enqueue a Celery task."""
        from app.modules.strategy_service.tasks import run_optimization_task

        strategy = await self.strategy_repository.get_by_user_and_id(user_id, strategy_id)
        if not strategy:
            raise ResourceNotFoundException("Strategy not found")

        run = OptimizationRun(
            user_id=user_id,
            strategy_id=strategy_id,
            status="PENDING",
            search_type=search_type,
            objective=objective,
            max_runs=max_runs,
            initial_capital=initial_capital,
            parameter_space_json=[p.model_dump() if hasattr(p, 'model_dump') else p for p in parameter_space],
            constraints_json=[c.model_dump() if hasattr(c, 'model_dump') else c for c in (constraints or [])],
        )
        created_run = await self.optimization_repository.create(run)

        task = run_optimization_task.delay(
            run_id=created_run.id,
            strategy_id=strategy_id,
            start_date_iso=start_date.isoformat(),
            end_date_iso=end_date.isoformat(),
            initial_capital=initial_capital,
            parameter_space_json=created_run.parameter_space_json,
            constraints_json=created_run.constraints_json or [],
            objective=objective,
            search_type=search_type,
            max_runs=max_runs,
        )
        return 202, {"run_id": created_run.id, "task_id": task.id, "status": "PENDING",
                     "message": "Optimization job enqueued successfully."}

    async def get_optimization_run(
        self, user_id: str, strategy_id: str, run_id: str
    ) -> tuple[int, OptimizationRunResponseSchema]:
        """Fetch a specific optimization run verifying ownership."""
        strategy = await self.strategy_repository.get_by_user_and_id(user_id, strategy_id)
        if not strategy:
            raise ResourceNotFoundException("Strategy not found")

        run = await self.optimization_repository.get_by_user_and_run_id(user_id, run_id)
        if not run or run.strategy_id != strategy_id:
            raise ResourceNotFoundException("Optimization run not found")

        return 200, OptimizationRunResponseSchema.model_validate(run)

    async def list_optimization_runs(
        self, user_id: str, strategy_id: str, page: int = 1, limit: int = 8
    ) -> tuple[int, PaginatedOptimizationRunsResponseSchema]:
        """Paginated list of optimization runs for a strategy."""
        strategy = await self.strategy_repository.get_by_user_and_id(user_id, strategy_id)
        if not strategy:
            raise ResourceNotFoundException("Strategy not found")

        data = await self.optimization_repository.get_runs_paginated(strategy_id, user_id, page, limit)
        return 200, PaginatedOptimizationRunsResponseSchema.model_validate(data)
