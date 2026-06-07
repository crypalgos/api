"""Tests for BacktestRepository."""

from unittest.mock import AsyncMock, MagicMock
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from app.modules.strategy_service.models.backtest_model import Backtest
from app.modules.strategy_service.repositories.backtest_repository import BacktestRepository


@pytest.fixture
def backtest_repo(mock_db_session: AsyncMock) -> BacktestRepository:
    """Create a backtest repository instance using shared mock_db_session."""
    return BacktestRepository(mock_db_session)


@pytest.mark.asyncio
async def test_get_by_strategy_id(backtest_repo: BacktestRepository, mock_db_session: AsyncMock) -> None:
    """Test retrieving backtests by strategy ID."""
    mock_backtests = [MagicMock(spec=Backtest), MagicMock(spec=Backtest)]
    mock_db_session.execute.return_value.scalars.return_value.all.return_value = mock_backtests

    result = await backtest_repo.get_by_strategy_id("strat-123")

    assert len(result) == 2
    assert result == mock_backtests
    mock_db_session.execute.assert_called_once()


@pytest.mark.asyncio
async def test_create_backtest(backtest_repo: BacktestRepository, mock_db_session: AsyncMock) -> None:
    """Test creating a backtest record."""
    bt = Backtest(id="bt-123", strategy_id="strat-123", exchange="binance", symbol="BTC/USDT")
    mock_db_session.refresh = AsyncMock()

    result = await backtest_repo.create(bt)

    assert result == bt
    mock_db_session.add.assert_called_once_with(bt)
    mock_db_session.commit.assert_called_once()
    mock_db_session.refresh.assert_called_once_with(bt)
