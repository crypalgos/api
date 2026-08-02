"""Regression test for WebsocketManager.broadcast()'s event.__dict__ bug —
the same AttributeError-on-slotted-dataclass issue as
PersistenceService.persist_event() (see test_persistence_service.py),
independently present here too. ExecutionRunner's handle_ws_broadcast
callback wraps this in an unawaited asyncio.create_task, so the failure was
silent — no real event has ever reached a connected WebSocket client through
this path.
"""
from unittest.mock import AsyncMock, MagicMock

from crypalgos_core.engine.context import ExecutionContext, ExecutionMode
from crypalgos_core.events.engine_events import OrderFilledEvent

from app.modules.strategy_service.services.websocket_manager import WebsocketManager


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


async def test_broadcast_sends_a_real_payload_built_from_to_dict() -> None:
    manager = WebsocketManager()
    fake_ws = MagicMock()
    fake_ws.send_text = AsyncMock()
    manager.active_connections["run-1"] = [fake_ws]

    await manager.broadcast("run-1", _make_event())

    fake_ws.send_text.assert_awaited_once()
    sent = fake_ws.send_text.call_args[0][0]
    assert '"event_type": "ORDER_FILLED"' in sent
    assert '"order_id": "o1"' in sent
