import logging
from typing import Any, Optional

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.base_repositories import BaseRepository
from app.modules.strategy_service.models.research_run_model import (
    ResearchRun,
    StrategyLatestResults,
)

logger = logging.getLogger(__name__)

class ResearchRunRepository(BaseRepository[ResearchRun]):
    def __init__(self, session: AsyncSession):
        super().__init__(session, ResearchRun)

    async def get_runs_paginated(
        self,
        strategy_id: Optional[str] = None,
        run_type: Optional[str] = None,
        status: Optional[str] = None,
        is_favorite: Optional[bool] = None,
        sort_by: str = "updated_at",
        page: int = 1,
        limit: int = 8
    ) -> dict[str, Any]:
        """Fetch a paginated, filtered list of research runs."""
        offset = (page - 1) * limit
        stmt = select(ResearchRun)
        count_stmt = select(func.count()).select_from(ResearchRun)

        filters = []
        if strategy_id:
            filters.append(ResearchRun.strategy_id == strategy_id)
        if run_type:
            filters.append(ResearchRun.type == run_type)
        if status:
            filters.append(ResearchRun.status == status)
        if is_favorite is not None:
            filters.append(ResearchRun.is_favorite == is_favorite)

        if filters:
            stmt = stmt.where(and_(*filters))
            count_stmt = count_stmt.where(and_(*filters))

        # Sorting
        if sort_by == "created_at":
            stmt = stmt.order_by(ResearchRun.created_at.desc())
        elif sort_by == "is_favorite":
            stmt = stmt.order_by(ResearchRun.is_favorite.desc(), ResearchRun.updated_at.desc())
        else:
            stmt = stmt.order_by(ResearchRun.updated_at.desc())

        total_query = await self.session.execute(count_stmt)
        total = total_query.scalar_one()

        items_query = await self.session.execute(stmt.offset(offset).limit(limit))
        items = list(items_query.scalars().all())

        total_pages = (total // limit) + (1 if total % limit > 0 else 0)

        return {
            "total": total,
            "runs": items,
            "current_page": page,
            "limit": limit,
            "total_pages": total_pages,
        }

    async def get_latest_results(self, strategy_id: str) -> StrategyLatestResults | None:
        """Fetch the latest runs mapping for a strategy."""
        stmt = select(StrategyLatestResults).where(StrategyLatestResults.strategy_id == strategy_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_latest_run(self, strategy_id: str, run_type: str, run_id: str) -> None:
        """Updates the latest results mapping record for a strategy."""
        stmt = select(StrategyLatestResults).where(StrategyLatestResults.strategy_id == strategy_id)
        result = await self.session.execute(stmt)
        record = result.scalar_one_or_none()

        if not record:
            record = StrategyLatestResults(strategy_id=strategy_id)
            self.session.add(record)

        col_name = f"latest_{run_type.lower()}_id"
        setattr(record, col_name, run_id)
        await self.session.commit()
