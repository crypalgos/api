"""Tests for StrategyRepository."""

from unittest.mock import AsyncMock, MagicMock
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from app.modules.strategy_service.models.strategy_model import Strategy
from app.modules.strategy_service.repositories.strategy_repository import StrategyRepository


@pytest.fixture
def strategy_repo(mock_db_session: AsyncMock) -> StrategyRepository:
    """Create a strategy repository instance using shared mock_db_session."""
    return StrategyRepository(mock_db_session)


@pytest.mark.asyncio
async def test_get_by_user_id(strategy_repo: StrategyRepository, mock_db_session: AsyncMock) -> None:
    """Test retrieving strategies by user ID."""
    mock_strategies = [MagicMock(spec=Strategy), MagicMock(spec=Strategy)]
    mock_db_session.execute.return_value.scalars.return_value.all.return_value = mock_strategies

    result = await strategy_repo.get_by_user_id("user-123")

    assert len(result) == 2
    assert result == mock_strategies
    mock_db_session.execute.assert_called_once()


@pytest.mark.asyncio
async def test_create_strategy(strategy_repo: StrategyRepository, mock_db_session: AsyncMock) -> None:
    """Test creating a strategy."""
    strat = Strategy(id="strat-123", user_id="user-123", name="Test Strat", canvas_json={}, compiled_code="")
    mock_db_session.refresh = AsyncMock()

    result = await strategy_repo.create(strat)

    assert result == strat
    mock_db_session.add.assert_called_once_with(strat)
    mock_db_session.commit.assert_called_once()
    mock_db_session.refresh.assert_called_once_with(strat)


@pytest.mark.asyncio
async def test_get_by_id(strategy_repo: StrategyRepository, mock_db_session: AsyncMock) -> None:
    """Test fetching strategy by ID."""
    strat = Strategy(id="strat-123")
    mock_db_session.get.return_value = strat

    result = await strategy_repo.get_by_id("strat-123")

    assert result == strat
    mock_db_session.get.assert_called_once_with(Strategy, "strat-123")


@pytest.mark.asyncio
async def test_update_strategy(strategy_repo: StrategyRepository, mock_db_session: AsyncMock) -> None:
    """Test updating strategy attributes."""
    strat = Strategy(id="strat-123", name="Old Name")
    mock_db_session.get.return_value = strat

    result = await strategy_repo.update("strat-123", name="New Name")

    assert result == strat
    assert strat.name == "New Name"
    mock_db_session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_delete_strategy_success(strategy_repo: StrategyRepository, mock_db_session: AsyncMock) -> None:
    """Test deleting strategy successfully."""
    strat = Strategy(id="strat-123")
    mock_db_session.get.return_value = strat

    result = await strategy_repo.delete("strat-123")

    assert result is True
    mock_db_session.execute.assert_called_once()
    mock_db_session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_delete_strategy_not_found(strategy_repo: StrategyRepository, mock_db_session: AsyncMock) -> None:
    """Test deleting non-existent strategy returns False."""
    mock_db_session.get.return_value = None

    result = await strategy_repo.delete("strat-non-existent")

    assert result is False
    mock_db_session.commit.assert_not_called()
