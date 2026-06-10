import logging
from typing import Any, Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.base_repositories import BaseRepository
from app.modules.strategy_service.models.walkforward_model import WalkForwardRun

logger = logging.getLogger(__name__)


class WalkForwardRepository(BaseRepository[WalkForwardRun]):
    def __init__(self, session: AsyncSession):
        super().__init__(session, WalkForwardRun)

    async def get_by_strategy_id(self, strategy_id: str) -> list[WalkForwardRun]:
        """Retrieve all walk-forward runs for a strategy ordered by most recent."""
        stmt = (
            select(WalkForwardRun)
            .where(WalkForwardRun.strategy_id == strategy_id)
            .order_by(WalkForwardRun.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_user_and_run_id(self, user_id: str, run_id: str) -> Optional[WalkForwardRun]:
        """Retrieve a specific walk-forward run verifying user ownership."""
        stmt = (
            select(WalkForwardRun)
            .where(WalkForwardRun.id == run_id, WalkForwardRun.user_id == user_id)
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
        """Paginated list of walk-forward runs for a strategy."""
        offset = (page - 1) * limit
        base = (
            select(WalkForwardRun)
            .where(WalkForwardRun.strategy_id == strategy_id, WalkForwardRun.user_id == user_id)
        )
        count_stmt = select(func.count()).select_from(WalkForwardRun).where(
            WalkForwardRun.strategy_id == strategy_id, WalkForwardRun.user_id == user_id
        )

        if search:
            search_filter = WalkForwardRun.objective.ilike(f"%{search}%")
            base = base.where(search_filter)
            count_stmt = count_stmt.where(search_filter)

        total = (await self.session.execute(count_stmt)).scalar_one()
        items = (await self.session.execute(base.order_by(WalkForwardRun.created_at.desc()).offset(offset).limit(limit))).scalars().all()

        return {
            "total": total,
            "runs": list(items),
            "current_page": page,
            "limit": limit,
            "total_pages": (total // limit) + (1 if total % limit > 0 else 0),
        }
