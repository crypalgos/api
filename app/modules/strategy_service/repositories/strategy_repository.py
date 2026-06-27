import logging
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.base_repositories import BaseRepository
from app.modules.strategy_service.models.strategy_model import Strategy

logger = logging.getLogger(__name__)

class StrategyRepository(BaseRepository[Strategy]):
    def __init__(self, session: AsyncSession):
        super().__init__(session, Strategy)

    async def get_by_user_id(self, user_id: str) -> list[Strategy]:
        """Retrieve all strategies belonging to a specific user."""
        stmt = select(Strategy).where(Strategy.user_id == user_id).order_by(Strategy.updated_at.desc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_user_and_id(self, user_id: str, strategy_id: str) -> Strategy | None:
        """Retrieve a single strategy owned by the specified user."""
        stmt = select(Strategy).where(
            Strategy.id == strategy_id, Strategy.user_id == user_id
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_strategies_paginated(
        self, user_id: str, page: int = 1, limit: int = 8, search: str = "", archived: bool = False
    ) -> dict[str, Any]:
        """Fetch a paginated list of strategies belonging to a user, with optional search filtering."""
        from sqlalchemy.orm import selectinload
        from app.modules.strategy_service.models.research_run_model import StrategyLatestResults

        offset = (page - 1) * limit
        stmt = select(Strategy).where(Strategy.user_id == user_id, Strategy.is_archived == archived).options(
            selectinload(Strategy.latest_results).selectinload(StrategyLatestResults.latest_backtest)
        )
        count_stmt = select(func.count()).select_from(Strategy).where(Strategy.user_id == user_id, Strategy.is_archived == archived)

        if search:
            search_filter = or_(
                Strategy.name.ilike(f"%{search}%"),
                Strategy.description.ilike(f"%{search}%")
            )
            stmt = stmt.where(search_filter)
            count_stmt = count_stmt.where(search_filter)

        stmt = stmt.order_by(Strategy.updated_at.desc())

        total_query = await self.session.execute(count_stmt)
        total = total_query.scalar_one()

        items_query = await self.session.execute(stmt.offset(offset).limit(limit))
        items = items_query.scalars().all()

        total_pages = (total // limit) + (1 if total % limit > 0 else 0)

        return {
            "total": total,
            "strategies": items,
            "current_page": page,
            "limit": limit,
            "total_pages": total_pages,
        }

