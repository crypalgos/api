"""EventPublisher._flush_locked() used to persist only d["payload"], dropping
every EngineEvent base field (sequence_number, candle_index, parent_sequence,
root_sequence, node_id, run_id, strategy_id) -- fields a trade-tree /
decision-replay view needs to reconstruct causal chains for a completed live
session. broadcast() already sends the full to_dict() over the live WS
unmerged; this only affects what's queryable afterwards via REST scrollback.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from crypalgos_core.engine.context import ExecutionContext, ExecutionMode
from crypalgos_core.events.engine_events import OrderFilledEvent

from app.modules.strategy_service.execution import event_publisher as pub_mod
from app.modules.strategy_service.execution.event_publisher import EventPublisher


def _make_event() -> OrderFilledEvent:
    context = ExecutionContext(
        strategy_run_id="run-1", user_id="user-1", mode=ExecutionMode.PAPER
    )
    return OrderFilledEvent(
        sequence_number=42,
        timestamp=1_700_000_000_000,
        candle_index=7,
        symbol_id="BTCUSD",
        parent_sequence=41,
        root_sequence=40,
        node_id="node-1",
        run_id="run-1",
        strategy_id="strat-1",
        context=context,
        order_id="o1",
        side="LONG",
        fill_price=100.0,
        fill_quantity=1.0,
        fee=0.0,
    )


async def test_flush_folds_base_engine_fields_into_payload(monkeypatch) -> None:
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

    monkeypatch.setattr(pub_mod, "AsyncSessionLocal", MockSession)

    publisher = EventPublisher(session_id="run-1")
    await publisher.persist([event])
    await publisher.flush()

    assert mock_commit.await_count == 1
    assert mock_add.call_count == 1
    db_event = mock_add.call_args[0][0]
    assert db_event.event_type == "ORDER_FILLED"

    # Subclass-only fields (payload's own contribution) still present.
    assert db_event.payload["order_id"] == "o1"
    assert db_event.payload["fill_price"] == 100.0

    # Base EngineEvent fields, previously dropped entirely, now folded in.
    assert db_event.payload["sequence_number"] == 42
    assert db_event.payload["candle_index"] == 7
    assert db_event.payload["parent_sequence"] == 41
    assert db_event.payload["root_sequence"] == 40
    assert db_event.payload["node_id"] == "node-1"
    assert db_event.payload["symbol_id"] == "BTCUSD"
