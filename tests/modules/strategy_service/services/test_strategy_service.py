"""Tests for StrategyService."""

from datetime import datetime, UTC
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.exceptions.exceptions import ResourceNotFoundException
from app.modules.strategy_service.models.strategy_model import Strategy
from app.modules.strategy_service.repositories.backtest_repository import BacktestRepository
from app.modules.strategy_service.repositories.strategy_repository import StrategyRepository
from app.modules.strategy_service.services.strategy_service import StrategyService


@pytest.fixture
def strategy_service(mock_strategy_repo: MagicMock, mock_backtest_repo: MagicMock) -> StrategyService:
    """Create StrategyService with shared mock repos."""
    return StrategyService(mock_strategy_repo, mock_backtest_repo)


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
    mock_compiler.compile_dag.assert_called_once_with({"nodes": [], "edges": []})


@pytest.mark.asyncio
@patch("app.modules.strategy_service.services.strategy_service.DAGCompiler")
async def test_create_strategy_compile_failure(
    mock_compiler: MagicMock,
    strategy_service: StrategyService,
    mock_strategy_repo: MagicMock
) -> None:
    """Test creating a strategy when canvas compilation fails (caches traceback/fallback)."""
    mock_compiler.compile_dag.side_effect = Exception("Syntax Error in DAG")
    
    mock_saved = Strategy(
        id="strat-123",
        user_id="user-123",
        name="My Strat",
        description="Desc",
        canvas_json={"nodes": [], "edges": []},
        compiled_code="# Compilation failed during strategy creation.\n",
        is_code_modified=False,
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
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC)
    )
    mock_strategy_repo.get_by_id.return_value = mock_saved

    code, result = await strategy_service.get_strategy("user-123", "strat-123")

    assert code == 200
    assert result.id == "strat-123"


@pytest.mark.asyncio
async def test_get_strategy_not_found(
    strategy_service: StrategyService,
    mock_strategy_repo: MagicMock
) -> None:
    """Test get_strategy raises ResourceNotFoundException if strategy is not found."""
    mock_strategy_repo.get_by_id.return_value = None

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
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC)
    )
    mock_strategy_repo.get_by_id.return_value = mock_saved

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
            is_code_modified=False, created_at=datetime.now(UTC), updated_at=datetime.now(UTC)
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
        user_id="user-123", page=1, limit=8, search=""
    )


@pytest.mark.asyncio
async def test_save_custom_code(
    strategy_service: StrategyService,
    mock_strategy_repo: MagicMock
) -> None:
    """Test saving Monaco custom edited code toggles code override flag."""
    mock_saved = Strategy(id="strat-123", user_id="user-123")
    mock_strategy_repo.get_by_id.return_value = mock_saved

    code, result = await strategy_service.save_custom_code("user-123", "strat-123", "print('hello')")

    assert code == 200
    assert result["success"] is True
    mock_strategy_repo.update.assert_called_once_with(
        "strat-123", compiled_code="print('hello')", is_code_modified=True
    )


@pytest.mark.asyncio
@patch("app.modules.strategy_service.services.strategy_service.DAGCompiler")
async def test_reset_to_visual_builder(
    mock_compiler: MagicMock,
    strategy_service: StrategyService,
    mock_strategy_repo: MagicMock
) -> None:
    """Test resetting strategy state to visual builder canvas re-compilation."""
    mock_compiler.compile_dag.return_value = "pristine_code"
    mock_strat = Strategy(id="strat-123", user_id="user-123", canvas_json={"x": 1})
    mock_strategy_repo.get_by_id.return_value = mock_strat

    mock_updated = Strategy(
        id="strat-123", user_id="user-123", name="S", canvas_json={"x": 1},
        compiled_code="pristine_code", is_code_modified=False,
        created_at=datetime.now(UTC), updated_at=datetime.now(UTC)
    )
    mock_strategy_repo.update.return_value = mock_updated

    code, result = await strategy_service.reset_to_visual_builder("user-123", "strat-123")

    assert code == 200
    assert result.is_code_modified is False
    assert result.compiled_code == "pristine_code"
    mock_compiler.compile_dag.assert_called_once_with({"x": 1})
    mock_strategy_repo.update.assert_called_once_with(
        "strat-123", compiled_code="pristine_code", is_code_modified=False
    )


@pytest.mark.asyncio
@patch("app.modules.strategy_service.services.strategy_service.settings.sandbox_enabled", True)
@patch("app.modules.strategy_service.tasks.run_asynchronous_backtest_task.delay")
@patch("app.modules.strategy_service.services.strategy_service.DAGCompiler")
async def test_trigger_backtest_success(
    mock_compiler: MagicMock,
    mock_delay: MagicMock,
    strategy_service: StrategyService,
    mock_strategy_repo: MagicMock
) -> None:
    """Test triggering asynchronous Celery backtest resolves exchange/symbol/leverage from canvas DataNode."""
    mock_compiler.compile_dag.return_value = "compiled_python_script"

    # Canvas JSON with a properly configured startNode and dataNode
    canvas_with_data_node = {
        "nodes": [
            {
                "id": "start-1",
                "type": "startNode",
                "data": {
                    "exchange": "delta",
                    "leverage": 10,
                },
            },
            {
                "id": "data-1",
                "type": "dataNode",
                "data": {
                    "symbol": "BTCUSDT",
                    "timeframe": "1h",
                },
            }
        ],
        "edges": [],
    }

    mock_strat = Strategy(
        id="strat-123",
        user_id="user-123",
        name="Backtest Strat",
        canvas_json=canvas_with_data_node,
        compiled_code="old_code",
        is_code_modified=False
    )
    mock_strategy_repo.get_by_id.return_value = mock_strat

    mock_task = MagicMock()
    mock_task.id = "celery-uuid-999"
    mock_delay.return_value = mock_task

    # New API: only pass dates and capital — no exchange/symbol/leverage
    code, result = await strategy_service.trigger_backtest(
        user_id="user-123",
        strategy_id="strat-123",
        start_date=datetime(2026, 1, 1),
        end_date=datetime(2026, 1, 2),
        initial_capital=5000.0,
    )

    assert code == 202
    assert result["status"] == "enqueued"
    assert result["task_id"] == "celery-uuid-999"

    # Verify visual code compiled and updated
    mock_compiler.compile_dag.assert_called_once_with(canvas_with_data_node)
    mock_strategy_repo.update.assert_called_once_with("strat-123", compiled_code="compiled_python_script")

    # Verify background Celery task enqueued with params resolved from dataNode
    mock_delay.assert_called_once_with(
        strategy_id="strat-123",
        exchange="delta",          # resolved from dataNode.data.source
        symbol="BTCUSDT",          # resolved from dataNode.data.symbol (no USDT stripping now)
        start_date_iso="2026-01-01T00:00:00",
        end_date_iso="2026-01-02T00:00:00",
        initial_capital=5000.0,
        leverage=10               # resolved from dataNode.data.leverage
    )


@pytest.mark.asyncio
async def test_trigger_backtest_missing_data_node(
    strategy_service: StrategyService,
    mock_strategy_repo: MagicMock
) -> None:
    """Test trigger_backtest raises ValueError when canvas has no DataNode configured."""
    mock_strat = Strategy(
        id="strat-123",
        user_id="user-123",
        name="No Data Node",
        canvas_json={"nodes": [{"id": "start-1", "type": "startNode", "data": {}}], "edges": []},
        compiled_code="",
        is_code_modified=False
    )
    mock_strategy_repo.get_by_id.return_value = mock_strat

    with pytest.raises(ValueError, match="no Data Node configured"):
        await strategy_service.trigger_backtest(
            user_id="user-123",
            strategy_id="strat-123",
            start_date=datetime(2026, 1, 1),
            end_date=datetime(2026, 1, 2),
            initial_capital=5000.0,
        )
