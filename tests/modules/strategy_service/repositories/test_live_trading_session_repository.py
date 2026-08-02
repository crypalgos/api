"""Crash-detection via heartbeat_at: a Celery worker that's killed outright
(pkill/SIGKILL/OOM) or never picks up the queued task never runs
LiveTradingRunner.run()'s own except/finally status transition, leaving a
session claiming STARTING/RUNNING/STOPPING forever. reap_if_stale() and its
callers are what reconcile that back to ERROR.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.strategy_service.models.live_trading_session_model import (
    LiveTradingSession,
)
from app.modules.strategy_service.repositories.live_trading_session_repository import (
    LiveTradingSessionRepository,
)


def _session(**overrides) -> LiveTradingSession:
    defaults = dict(
        id="sess-1",
        strategy_id="strat-1",
        mode="PAPER",
        broker="delta",
        status="RUNNING",
        heartbeat_at=None,
        updated_at=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    return LiveTradingSession(**defaults)


@pytest.fixture
def repo(mock_db_session: AsyncMock) -> LiveTradingSessionRepository:
    return LiveTradingSessionRepository(mock_db_session)


@pytest.mark.asyncio
async def test_reap_if_stale_leaves_healthy_running_session_untouched(
    repo: LiveTradingSessionRepository, mock_db_session: AsyncMock
) -> None:
    live_session = _session(
        status="RUNNING", heartbeat_at=datetime.now(timezone.utc)
    )

    result = await repo.reap_if_stale(live_session)

    assert result.status == "RUNNING"
    mock_db_session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_reap_if_stale_marks_stale_running_session_as_error(
    repo: LiveTradingSessionRepository, mock_db_session: AsyncMock
) -> None:
    stale_heartbeat = datetime.now(timezone.utc) - timedelta(seconds=60)
    live_session = _session(status="RUNNING", heartbeat_at=stale_heartbeat)

    result = await repo.reap_if_stale(live_session)

    assert result.status == "ERROR"
    assert result.error_msg is not None
    assert result.stopped_at is not None
    mock_db_session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_reap_if_stale_marks_stale_starting_session_as_error(
    repo: LiveTradingSessionRepository, mock_db_session: AsyncMock
) -> None:
    """STARTING sessions have no heartbeat yet -- staleness falls back to
    updated_at (bootstrap never got far enough to send a heartbeat)."""
    stale_updated_at = datetime.now(timezone.utc) - timedelta(seconds=120)
    live_session = _session(
        status="STARTING", heartbeat_at=None, updated_at=stale_updated_at
    )

    result = await repo.reap_if_stale(live_session)

    assert result.status == "ERROR"
    mock_db_session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_reap_if_stale_ignores_terminal_statuses(
    repo: LiveTradingSessionRepository, mock_db_session: AsyncMock
) -> None:
    ancient = datetime.now(timezone.utc) - timedelta(days=1)
    live_session = _session(status="STOPPED", heartbeat_at=ancient)

    result = await repo.reap_if_stale(live_session)

    assert result.status == "STOPPED"
    mock_db_session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_get_active_session_returns_none_for_stale_running_session(
    repo: LiveTradingSessionRepository, mock_db_session: AsyncMock
) -> None:
    """The exact bug this reaper fixes: a dead session must not block a new
    one from starting (LiveServiceMixin.start_live_session's
    get_active_session() guard)."""
    stale_heartbeat = datetime.now(timezone.utc) - timedelta(seconds=60)
    live_session = _session(status="RUNNING", heartbeat_at=stale_heartbeat)

    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = live_session
    mock_db_session.execute = AsyncMock(return_value=mock_result)

    result = await repo.get_active_session("strat-1")

    assert result is None
    assert live_session.status == "ERROR"


@pytest.mark.asyncio
async def test_get_active_session_returns_healthy_session_unchanged(
    repo: LiveTradingSessionRepository, mock_db_session: AsyncMock
) -> None:
    live_session = _session(status="RUNNING", heartbeat_at=datetime.now(timezone.utc))

    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = live_session
    mock_db_session.execute = AsyncMock(return_value=mock_result)

    result = await repo.get_active_session("strat-1")

    assert result is live_session
    assert result.status == "RUNNING"
