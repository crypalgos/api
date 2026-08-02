"""Regression coverage for the live-task async engine lifecycle."""

from unittest.mock import AsyncMock, MagicMock

import app.modules.strategy_service.tasks.live_trading_tasks as live_tasks_mod
from app.modules.strategy_service.tasks.live_trading_tasks import run_live_trading_task


def test_run_live_trading_task_disposes_async_engine_after_runner(monkeypatch) -> None:
    """The pool must close on the asyncio.run() loop, never sync-dispose first."""
    call_order: list[str] = []

    async def record_dispose() -> None:
        call_order.append("dispose")

    mock_dispose = AsyncMock(side_effect=record_dispose)
    mock_engine = MagicMock()
    mock_engine.dispose = mock_dispose
    monkeypatch.setattr("app.db.connect_db.engine", mock_engine, raising=True)

    mock_runner_instance = MagicMock()

    async def record_run() -> None:
        call_order.append("run")

    mock_runner_instance.run = AsyncMock(side_effect=record_run)
    mock_runner_cls = MagicMock(return_value=mock_runner_instance)
    monkeypatch.setattr(live_tasks_mod, "LiveTradingRunner", mock_runner_cls)

    run_live_trading_task.run(session_id="sess-1")

    mock_runner_cls.assert_called_once()
    mock_runner_instance.run.assert_awaited_once()
    mock_dispose.assert_awaited_once()
    assert call_order == ["run", "dispose"]
