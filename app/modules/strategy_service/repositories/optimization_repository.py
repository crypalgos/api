import logging
from typing import Any, Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.base_repositories import BaseRepository
from app.modules.strategy_service.models.optimization_model import OptimizationRun

logger = logging.getLogger(__name__)


class OptimizationRepository(BaseRepository[OptimizationRun]):
    def __init__(self, session: AsyncSession):
        super().__init__(session, OptimizationRun)

    async def get_by_strategy_id(self, strategy_id: str) -> list[OptimizationRun]:
        """Retrieve all optimization runs for a strategy ordered by most recent."""
        stmt = (
            select(OptimizationRun)
            .where(OptimizationRun.strategy_id == strategy_id)
            .order_by(OptimizationRun.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_user_and_run_id(self, user_id: str, run_id: str) -> Optional[OptimizationRun]:
        """Retrieve a specific optimization run verifying user ownership."""
        stmt = (
            select(OptimizationRun)
            .where(OptimizationRun.id == run_id, OptimizationRun.user_id == user_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_status(self, run_id: str, status: str, **fields: Any) -> None:
        """Update the status and any extra fields atomically."""
        run = await self.get_by_id(run_id)
        if run:
            run.status = status
            for k, v in fields.items():
                setattr(run, k, v)
            await self.session.flush()

    async def get_runs_paginated(
        self, strategy_id: str, user_id: str, page: int = 1, limit: int = 8
    ) -> dict[str, Any]:
        """Paginated list of optimization runs for a strategy."""
        offset = (page - 1) * limit
        base = (
            select(OptimizationRun)
            .where(OptimizationRun.strategy_id == strategy_id, OptimizationRun.user_id == user_id)
        )
        count_stmt = select(func.count()).select_from(OptimizationRun).where(
            OptimizationRun.strategy_id == strategy_id, OptimizationRun.user_id == user_id
        )

        total = (await self.session.execute(count_stmt)).scalar_one()
        items = (await self.session.execute(base.order_by(OptimizationRun.created_at.desc()).offset(offset).limit(limit))).scalars().all()

        return {
            "total": total,
            "runs": list(items),
            "current_page": page,
            "limit": limit,
            "total_pages": (total // limit) + (1 if total % limit > 0 else 0),
        }
