"""Tests for StrategyService."""

from datetime import datetime, UTC
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.exceptions.exceptions import ResourceNotFoundException
from app.modules.strategy_service.models.strategy_model import Strategy
from app.modules.strategy_service.repositories.strategy_repository import StrategyRepository
from app.modules.strategy_service.services.strategy_service import StrategyService


@pytest.fixture
def strategy_service(mock_strategy_repo: MagicMock) -> StrategyService:
    """Create StrategyService with shared mock repos."""
    return StrategyService(mock_strategy_repo)


@pytest.mark.asyncio
@patch("app.modules.strategy_service.services.strategy_service.DAGCompiler")
async def test_create_strategy_success(
    mock_compiler: MagicMock,
    strategy_service: StrategyService,
    mock_strategy_repo: MagicMock
) -> None:
    """Test creating a strategy successfully compiles React Flow DAG canvas to code."""
    mock_compiler.compile_dag.return_value = "class MockStrategy: pass"
    
    mock_saved = Strategy(
        id="strat-123",
        user_id="user-123",
        name="My Strat",
        description="Desc",
        canvas_json={"nodes": [], "edges": []},
        compiled_code="class MockStrategy: pass",
        is_code_modified=False,
        is_template=False,
        is_archived=False,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC)
    )
    mock_strategy_repo.create.return_value = mock_saved

    code, result = await strategy_service.create_strategy(
        user_id="user-123",
        name="My Strat",
        description="Desc",
        canvas_json={"nodes": [], "edges": []}
    )

    assert code == 201
    assert result.id == "strat-123"
    assert result.compiled_code == "class MockStrategy: pass"
    mock_strategy_repo.create.assert_called_once()
    mock_compiler.return_value.compile_dag.assert_called_once_with({"nodes": [], "edges": []})


@pytest.mark.asyncio
@patch("app.modules.strategy_service.services.strategy_service.DAGCompiler")
async def test_create_strategy_compile_failure(
    mock_compiler: MagicMock,
    strategy_service: StrategyService,
    mock_strategy_repo: MagicMock
) -> None:
    """Test creating a strategy when canvas compilation fails (caches traceback/fallback)."""
    mock_compiler.return_value.compile_dag.side_effect = Exception("Syntax Error in DAG")
    
    mock_saved = Strategy(
        id="strat-123",
        user_id="user-123",
        name="My Strat",
        description="Desc",
        canvas_json={"nodes": [], "edges": []},
        compiled_code="# Compilation failed during strategy creation.\n",
        is_code_modified=False,
        is_template=False,
        is_archived=False,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC)
    )
    mock_strategy_repo.create.return_value = mock_saved

    code, result = await strategy_service.create_strategy(
        user_id="user-123",
        name="My Strat",
        description="Desc",
        canvas_json={"nodes": [], "edges": []}
    )

    assert code == 201
    assert result.compiled_code.startswith("# Compilation failed")
    mock_strategy_repo.create.assert_called_once()


@pytest.mark.asyncio
async def test_get_strategy_success(
    strategy_service: StrategyService,
    mock_strategy_repo: MagicMock
) -> None:
    """Test fetching strategy by ID for authorized user."""
    mock_saved = Strategy(
        id="strat-123",
        user_id="user-123",
        name="My Strat",
        canvas_json={},
        compiled_code="",
        is_code_modified=False,
        is_template=False,
        is_archived=False,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC)
    )
    mock_strategy_repo.get_by_user_and_id.return_value = mock_saved

    code, result = await strategy_service.get_strategy("user-123", "strat-123")

    assert code == 200
    assert result.id == "strat-123"


@pytest.mark.asyncio
async def test_get_strategy_not_found(
    strategy_service: StrategyService,
    mock_strategy_repo: MagicMock
) -> None:
    """Test get_strategy raises ResourceNotFoundException if strategy is not found."""
    mock_strategy_repo.get_by_user_and_id.return_value = None

    with pytest.raises(ResourceNotFoundException):
        await strategy_service.get_strategy("user-123", "strat-123")


@pytest.mark.asyncio
async def test_get_strategy_unauthorized(
    strategy_service: StrategyService,
    mock_strategy_repo: MagicMock
) -> None:
    """Test get_strategy raises ResourceNotFoundException if user doesn't own it."""
    mock_saved = Strategy(
        id="strat-123",
        user_id="another-user",
        name="My Strat",
        canvas_json={},
        compiled_code="",
        is_code_modified=False,
        is_template=False,
        is_archived=False,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC)
    )
    mock_strategy_repo.get_by_user_and_id.return_value = None

    with pytest.raises(ResourceNotFoundException):
        await strategy_service.get_strategy("user-123", "strat-123")


@pytest.mark.asyncio
async def test_list_strategies(
    strategy_service: StrategyService,
    mock_strategy_repo: MagicMock
) -> None:
    """Test listing user strategies with pagination."""
    mock_list = [
        Strategy(
            id="strat-1", user_id="user-123", name="S1", canvas_json={}, compiled_code="",
            is_code_modified=False, is_template=False, is_archived=False, created_at=datetime.now(UTC), updated_at=datetime.now(UTC)
        )
    ]
    mock_strategy_repo.get_strategies_paginated.return_value = {
        "total": 1,
        "strategies": mock_list,
        "current_page": 1,
        "limit": 8,
        "total_pages": 1
    }

    code, result = await strategy_service.list_strategies("user-123")

    assert code == 200
    assert result.total == 1
    assert len(result.strategies) == 1
    assert result.strategies[0].id == "strat-1"
    mock_strategy_repo.get_strategies_paginated.assert_called_once_with(
        "user-123", 1, 8, ""
    )


@pytest.mark.asyncio
async def test_save_strategy_code(
    strategy_service: StrategyService,
    mock_strategy_repo: MagicMock
) -> None:
    """Test saving Monaco custom edited code toggles code override flag."""
    mock_saved = Strategy(id="strat-123", user_id="user-123", is_template=False, is_archived=False)
    mock_strategy_repo.get_by_user_and_id.return_value = mock_saved
    
    mock_updated = Strategy(
        id="strat-123", user_id="user-123", name="S", canvas_json={},
        compiled_code="print('hello')", is_code_modified=True,
        is_template=False, is_archived=False,
        created_at=datetime.now(UTC), updated_at=datetime.now(UTC)
    )
    mock_strategy_repo.update.return_value = mock_updated

    code, result = await strategy_service.save_strategy_code("user-123", "strat-123", "print('hello')")

    assert code == 200
    assert result.compiled_code == "print('hello')"
    assert result.is_code_modified is True
    mock_strategy_repo.update.assert_called_once_with("strat-123")


@pytest.mark.asyncio
@patch("app.modules.strategy_service.services.strategy_service.DAGCompiler")
async def test_reset_to_visual_builder(
    mock_compiler: MagicMock,
    strategy_service: StrategyService,
    mock_strategy_repo: MagicMock
) -> None:
    """Test resetting strategy state to visual builder canvas re-compilation."""
    mock_compiler.return_value.compile_dag.return_value = "pristine_code"
    mock_strat = Strategy(id="strat-123", user_id="user-123", canvas_json={"x": 1}, is_template=False, is_archived=False)
    mock_strategy_repo.get_by_user_and_id.return_value = mock_strat

    mock_updated = Strategy(
        id="strat-123", user_id="user-123", name="S", canvas_json={"x": 1},
        compiled_code="pristine_code", is_code_modified=False,
        is_template=False, is_archived=False,
        created_at=datetime.now(UTC), updated_at=datetime.now(UTC)
    )
    mock_strategy_repo.update.return_value = mock_updated

    code, result = await strategy_service.reset_to_visual_builder("user-123", "strat-123")

    assert code == 200
    assert result.is_code_modified is False
    assert result.compiled_code == "pristine_code"
    mock_compiler.return_value.compile_dag.assert_called_once_with({"x": 1})
    mock_strategy_repo.update.assert_called_once_with("strat-123")


@pytest.mark.asyncio
async def test_delete_strategy_soft_delete(
    strategy_service: StrategyService,
    mock_strategy_repo: MagicMock
) -> None:
    """Test delete_strategy sets is_archived=True on active strategy."""
    mock_strat = Strategy(id="strat-123", user_id="user-123", is_archived=False)
    mock_strategy_repo.get_by_user_and_id.return_value = mock_strat

    code, result = await strategy_service.delete_strategy("user-123", "strat-123")

    assert code == 200
    assert result["success"] is True
    assert result["message"] == "Strategy archived successfully."
    assert mock_strat.is_archived is True
    mock_strategy_repo.update.assert_called_once_with("strat-123")


@pytest.mark.asyncio
@patch("app.modules.strategy_service.services.strategy_service.storage_service")
async def test_delete_strategy_hard_delete(
    mock_storage: MagicMock,
    strategy_service: StrategyService,
    mock_strategy_repo: MagicMock
) -> None:
    """Test delete_strategy hard deletes strategy/runs and cleans S3 if already archived."""
    mock_storage.delete_directory = AsyncMock()
    mock_strat = Strategy(id="strat-123", user_id="user-123", is_archived=True)
    mock_strategy_repo.get_by_user_and_id.return_value = mock_strat

    mock_strategy_repo.session = AsyncMock()

    code, result = await strategy_service.delete_strategy("user-123", "strat-123")

    assert code == 200
    assert result["success"] is True
    assert "permanently deleted" in result["message"]
    mock_storage.delete_directory.assert_called_once_with("reports/strat-123")
    assert mock_strategy_repo.session.execute.call_count == 3
    mock_strategy_repo.session.commit.assert_called_once()
