from unittest.mock import AsyncMock, MagicMock
import pytest
from app.modules.strategy_service.models.research_run_model import ResearchRun
from app.modules.strategy_service.repositories.research_run_repository import ResearchRunRepository


@pytest.fixture
def run_repo(mock_db_session: AsyncMock) -> ResearchRunRepository:
    return ResearchRunRepository(mock_db_session)


@pytest.mark.asyncio
async def test_create_run(run_repo: ResearchRunRepository, mock_db_session: AsyncMock) -> None:
    run = ResearchRun(id="run-123", strategy_id="strat-123", type="BACKTEST", name="Test Run")
    mock_db_session.refresh = AsyncMock()

    result = await run_repo.create(run)

    assert result == run
    mock_db_session.add.assert_called_once_with(run)
    mock_db_session.commit.assert_called_once()
