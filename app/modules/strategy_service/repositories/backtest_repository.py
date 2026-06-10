import logging

from typing import Any
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.base_repositories import BaseRepository
from app.modules.strategy_service.models.backtest_model import Backtest

logger = logging.getLogger(__name__)

class BacktestRepository(BaseRepository[Backtest]):
    def __init__(self, session: AsyncSession):
        super().__init__(session, Backtest)

    async def get_by_strategy_id(self, strategy_id: str) -> list[Backtest]:
        """Retrieve all backtests belonging to a specific strategy."""
        stmt = select(Backtest).where(Backtest.strategy_id == strategy_id).order_by(Backtest.created_at.desc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_backtests_paginated(
        self, strategy_id: str, page: int = 1, limit: int = 8
    ) -> dict[str, Any]:
        """Retrieve a paginated, filtered list of backtests belonging to a strategy."""
        offset = (page - 1) * limit
        stmt = select(Backtest).where(Backtest.strategy_id == strategy_id)
        count_stmt = select(func.count()).select_from(Backtest).where(Backtest.strategy_id == strategy_id)

        stmt = stmt.order_by(Backtest.created_at.desc())

        total_query = await self.session.execute(count_stmt)
        total = total_query.scalar_one()

        items_query = await self.session.execute(stmt.offset(offset).limit(limit))
        items = items_query.scalars().all()

        total_pages = (total // limit) + (1 if total % limit > 0 else 0)

        return {
            "total": total,
            "backtests": items,
            "current_page": page,
            "limit": limit,
            "total_pages": total_pages,
        }
