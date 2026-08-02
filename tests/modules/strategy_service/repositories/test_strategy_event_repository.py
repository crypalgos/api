"""Regression test for StrategyEventRepository.list_for_session()'s ordering
bug: the no-`since` (initial snapshot) path used to be
`ORDER BY created_at ASC LIMIT N` unconditionally -- which returns the
OLDEST N rows. For any session with more than N events total, the initial
WS/REST snapshot got stuck showing only the beginning forever, never
advancing to recent activity. Fixed to fetch the most recent N rows and
restore chronological order for display; the `since` (reconnect) path is
unaffected -- ascending-from-a-cutoff is the correct semantics there.
"""

from unittest.mock import AsyncMock, MagicMock

from app.modules.strategy_service.repositories.strategy_event_repository import (
    StrategyEventRepository,
)


async def test_no_since_reverses_the_query_to_restore_chronological_order(
    mock_db_session: AsyncMock,
) -> None:
    repo = StrategyEventRepository(mock_db_session)

    # Simulates the DB returning rows ORDER BY created_at DESC (newest
    # first) -- the repository must reverse this back to oldest-first for
    # display, proving it queries DESC (most recent N) rather than ASC
    # (oldest N, the bug).
    newest_first = ["event-newest", "event-middle", "event-oldest"]
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = newest_first
    mock_db_session.execute = AsyncMock(return_value=mock_result)

    result = await repo.list_for_session("sess-1", since=None, limit=3)

    assert result == ["event-oldest", "event-middle", "event-newest"]


async def test_since_provided_does_not_reverse(mock_db_session: AsyncMock) -> None:
    repo = StrategyEventRepository(mock_db_session)

    oldest_first = ["event-a", "event-b", "event-c"]
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = oldest_first
    mock_db_session.execute = AsyncMock(return_value=mock_result)

    from datetime import datetime, timezone

    result = await repo.list_for_session(
        "sess-1", since=datetime.now(timezone.utc), limit=3
    )

    assert result == oldest_first
