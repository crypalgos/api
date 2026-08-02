"""Regression test for PersistenceService.persist_event()'s event.__dict__ bug.

EngineEvent subclasses are `@dataclass(slots=True, kw_only=True)` — instances
have no `__dict__`. persist_event() used to build its payload from
`event.__dict__.items()`, which raises AttributeError on every real call.
The caller (ExecutionRunner) wraps this in an unawaited asyncio.create_task,
so the failure was silent — nothing was ever actually persisted through this
path. This test proves both the historical failure mode and the fix.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from crypalgos_core.engine.context import ExecutionContext, ExecutionMode
from crypalgos_core.events.engine_events import OrderFilledEvent

from app.modules.strategy_service.services import persistence_service as svc_mod
from app.modules.strategy_service.services.persistence_service import (
    PersistenceService,
)


def _make_event() -> OrderFilledEvent:
    context = ExecutionContext(
        strategy_run_id="run-1", user_id="user-1", mode=ExecutionMode.PAPER
    )
    return OrderFilledEvent(
        sequence_number=1,
        timestamp=1_000,
        symbol_id="BTCUSD",
        context=context,
        order_id="o1",
        side="LONG",
        fill_price=100.0,
        fill_quantity=1.0,
        fee=0.0,
    )


def test_engine_events_have_no_instance_dict() -> None:
    """Confirms the root cause: slotted dataclasses have no __dict__, so the
    old `event.__dict__.items()` approach was never viable."""
    event = _make_event()
    with pytest.raises(AttributeError):
        _ = event.__dict__


async def test_persist_event_writes_type_and_payload_from_to_dict(monkeypatch) -> None:
    event = _make_event()

    mock_add = MagicMock()
    mock_commit = AsyncMock()

    class MockSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            pass

        add = mock_add
        commit = mock_commit

    monkeypatch.setattr(svc_mod, "AsyncSessionLocal", MockSession)

    await PersistenceService.persist_event(event)

    assert mock_commit.await_count == 1
    assert mock_add.call_count == 1
    db_event = mock_add.call_args[0][0]
    assert db_event.strategy_run_id == "run-1"
    assert db_event.event_type == "ORDER_FILLED"
    assert db_event.payload["order_id"] == "o1"
    assert db_event.payload["fill_price"] == 100.0
