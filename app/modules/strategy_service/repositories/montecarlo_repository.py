import logging
from typing import Any, Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.base_repositories import BaseRepository
from app.modules.strategy_service.models.montecarlo_model import MonteCarloRun

logger = logging.getLogger(__name__)


class MonteCarloRepository(BaseRepository[MonteCarloRun]):
    def __init__(self, session: AsyncSession):
        super().__init__(session, MonteCarloRun)

    async def get_by_strategy_id(self, strategy_id: str) -> list[MonteCarloRun]:
        """Retrieve all monte carlo runs for a strategy ordered by most recent."""
        stmt = (
            select(MonteCarloRun)
            .where(MonteCarloRun.strategy_id == strategy_id)
            .order_by(MonteCarloRun.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_user_and_run_id(self, user_id: str, run_id: str) -> Optional[MonteCarloRun]:
        """Retrieve a specific monte carlo run verifying user ownership."""
        stmt = (
            select(MonteCarloRun)
            .where(MonteCarloRun.id == run_id, MonteCarloRun.user_id == user_id)
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
        self, strategy_id: str, user_id: str, page: int = 1, limit: int = 8, search: str = ""
    ) -> dict[str, Any]:
        """Paginated list of monte carlo runs for a strategy."""
        offset = (page - 1) * limit
        base = (
            select(MonteCarloRun)
            .where(MonteCarloRun.strategy_id == strategy_id, MonteCarloRun.user_id == user_id)
        )
        count_stmt = select(func.count()).select_from(MonteCarloRun).where(
            MonteCarloRun.strategy_id == strategy_id, MonteCarloRun.user_id == user_id
        )

        if search:
            search_filter = MonteCarloRun.method.ilike(f"%{search}%")
            base = base.where(search_filter)
            count_stmt = count_stmt.where(search_filter)

        total = (await self.session.execute(count_stmt)).scalar_one()
        items = (await self.session.execute(base.order_by(MonteCarloRun.created_at.desc()).offset(offset).limit(limit))).scalars().all()

        return {
            "total": total,
            "runs": list(items),
            "current_page": page,
            "limit": limit,
            "total_pages": (total // limit) + (1 if total % limit > 0 else 0),
        }
