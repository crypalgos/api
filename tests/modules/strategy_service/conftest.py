"""Shared fixtures for strategy service tests."""

from datetime import datetime, UTC
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.middlewares.auth_middleware import get_current_user
from app.modules.strategy_service.routes.strategy_routes import get_strategy_service
from app.modules.strategy_service.models.strategy_model import Strategy
from app.modules.strategy_service.models.research_run_model import ResearchRun
from app.modules.strategy_service.repositories.strategy_repository import StrategyRepository
from app.modules.strategy_service.repositories.research_run_repository import ResearchRunRepository
from app.modules.strategy_service.services.strategy_service import StrategyService
from app.modules.strategy_service.schema.strategy_schema import StrategyResponseSchema
from fastapi.testclient import TestClient


@pytest.fixture
def client() -> TestClient:
    """Create a test client."""
    return TestClient(app)



@pytest.fixture
def mock_db_session() -> AsyncMock:
    """Create a mock database session."""
    session = AsyncMock(spec=AsyncSession)
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.refresh = AsyncMock()
    session.close = AsyncMock()

    mock_result = AsyncMock()
    mock_scalars = MagicMock()
    mock_scalars.all = MagicMock(return_value=[])
    mock_result.scalars = MagicMock(return_value=mock_scalars)
    session.execute = AsyncMock(return_value=mock_result)

    return session


@pytest.fixture
def mock_strategy_repo(mock_db_session: AsyncMock) -> MagicMock:
    """Create mock StrategyRepository."""
    repo = MagicMock(spec=StrategyRepository)
    repo.session = mock_db_session
    repo.create = AsyncMock()
    repo.get_by_id = AsyncMock()
    repo.get_by_user_and_id = AsyncMock()
    repo.get_by_user_id = AsyncMock()
    repo.update = AsyncMock()
    repo.delete = AsyncMock()
    return repo


@pytest.fixture
def mock_run_repo(mock_db_session: AsyncMock) -> MagicMock:
    """Create mock ResearchRunRepository."""
    repo = MagicMock(spec=ResearchRunRepository)
    repo.session = mock_db_session
    repo.create = AsyncMock()
    repo.get_runs_paginated = AsyncMock()
    repo.get_latest_results = AsyncMock()
    repo.update_latest_run = AsyncMock()
    return repo


@pytest.fixture
def mock_strategy_service() -> MagicMock:
    """Create a mock strategy service."""
    service = MagicMock()
    service.create_strategy = AsyncMock()
    service.get_strategy = AsyncMock()
    service.list_strategies = AsyncMock()
    service.save_custom_code = AsyncMock()
    service.reset_to_visual_builder = AsyncMock()
    service.trigger_backtest = AsyncMock()
    return service


@pytest.fixture
def override_strategy_service(mock_strategy_service: MagicMock):
    """Override the strategy service dependency."""
    async def _get_strategy_service_override():
        return mock_strategy_service

    app.dependency_overrides[get_strategy_service] = _get_strategy_service_override
    yield mock_strategy_service
    if get_strategy_service in app.dependency_overrides:
        del app.dependency_overrides[get_strategy_service]


@pytest.fixture
def override_current_user():
    """Override the get_current_user dependency."""
    async def _get_current_user_override():
        return {"user_id": "test-user-id"}

    app.dependency_overrides[get_current_user] = _get_current_user_override
    yield "test-user-id"
    if get_current_user in app.dependency_overrides:
        del app.dependency_overrides[get_current_user]


@pytest.fixture
def sample_strategy() -> Strategy:
    """Create a sample compiled python strategy class."""
    return Strategy(
        id="strat-123",
        user_id="user-123",
        name="Mock Quant Strategy",
        canvas_json={},
        compiled_code="""
from crypalgos_core.runtime.strategy_base import StrategyBase
class MyMockQuantStrategy(StrategyBase):
    datasources = {'btc': {'symbol': 'BTCUSD', 'leverage': 1, 'timeframes': ['1h']}}
    exchange = 'delta'
    def initialize(self):
        pass
    def on_data(self, candle):
        pass
""",
        is_code_modified=False,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC)
    )
