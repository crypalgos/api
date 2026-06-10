import logging
from datetime import datetime
from typing import Optional

from app.exceptions.exceptions import ResourceNotFoundException
from app.modules.strategy_service.models.walkforward_model import WalkForwardRun
from app.modules.strategy_service.repositories.walkforward_repository import WalkForwardRepository
from app.modules.strategy_service.repositories.strategy_repository import StrategyRepository
from app.modules.strategy_service.schema.strategy_schema import (
    WalkForwardRunResponseSchema,
    PaginatedWalkForwardRunsResponseSchema,
)

logger = logging.getLogger(__name__)

class WalkForwardService:
    def __init__(
        self,
        strategy_repository: StrategyRepository,
        walkforward_repository: WalkForwardRepository
    ):
        self.strategy_repository = strategy_repository
        self.walkforward_repository = walkforward_repository

    async def trigger_walkforward(
        self,
        user_id: str,
        strategy_id: str,
        start_date: datetime,
        end_date: datetime,
        parameter_space: list,
        objective: str,
        train_period_months: int,
        test_period_months: int,
        step_months: int,
        constraints: Optional[list],
        initial_capital: float,
        window_type: str,
    ) -> tuple[int, dict]:
        """Submit a walk-forward validation job and enqueue a Celery task."""
        from app.modules.strategy_service.tasks import run_walkforward_task

        strategy = await self.strategy_repository.get_by_user_and_id(user_id, strategy_id)
        if not strategy:
            raise ResourceNotFoundException("Strategy not found")

        window_config = {
            "train_period_months": train_period_months,
            "test_period_months": test_period_months,
            "step_months": step_months,
            "parameter_space": [p.model_dump() if hasattr(p, 'model_dump') else p for p in parameter_space],
            "constraints": [c.model_dump() if hasattr(c, 'model_dump') else c for c in (constraints or [])],
        }

        run = WalkForwardRun(
            user_id=user_id,
            strategy_id=strategy_id,
            status="PENDING",
            window_type=window_type,
            objective=objective,
            initial_capital=initial_capital,
            window_config_json=window_config,
        )
        created_run = await self.walkforward_repository.create(run)

        task = run_walkforward_task.delay(
            run_id=created_run.id,
            strategy_id=strategy_id,
            start_date_iso=start_date.isoformat(),
            end_date_iso=end_date.isoformat(),
            initial_capital=initial_capital,
            window_config_json=window_config,
            objective=objective,
        )
        return 202, {"run_id": created_run.id, "task_id": task.id, "status": "PENDING",
                     "message": "Walk-forward job enqueued successfully."}

    async def get_walkforward_run(
        self, user_id: str, strategy_id: str, run_id: str
    ) -> tuple[int, WalkForwardRunResponseSchema]:
        """Fetch a specific walk-forward run verifying ownership."""
        strategy = await self.strategy_repository.get_by_user_and_id(user_id, strategy_id)
        if not strategy:
            raise ResourceNotFoundException("Strategy not found")

        run = await self.walkforward_repository.get_by_user_and_run_id(user_id, run_id)
        if not run or run.strategy_id != strategy_id:
            raise ResourceNotFoundException("Walk-forward run not found")

        return 200, WalkForwardRunResponseSchema.model_validate(run)

    async def list_walkforward_runs(
        self, user_id: str, strategy_id: str, page: int = 1, limit: int = 8, search: str = ""
    ) -> tuple[int, PaginatedWalkForwardRunsResponseSchema]:
        """Paginated list of walk-forward runs for a strategy."""
        strategy = await self.strategy_repository.get_by_user_and_id(user_id, strategy_id)
        if not strategy:
            raise ResourceNotFoundException("Strategy not found")

        data = await self.walkforward_repository.get_runs_paginated(strategy_id, user_id, page, limit, search)
        return 200, PaginatedWalkForwardRunsResponseSchema.model_validate(data)
