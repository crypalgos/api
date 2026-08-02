"""Regression test for live_session_ws()'s datetime serialization crash.

WebSocket.send_json() calls plain json.dumps() with no `default=` handler --
every timeline event's `created_at` is a real datetime, so the very first
message on every connection crashed unconditionally with
"TypeError: Object of type datetime is not JSON serializable", closing the
socket immediately. The frontend's reconnect logic then repeated the same
crash forever -- an active/running live session's chart never received any
data because the TIMELINE_SNAPSHOT hydration never actually completed.
"""

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from app.main import app
from app.modules.strategy_service.routes.strategy_routes import get_strategy_service


def _make_mock_service():
    service = MagicMock()
    service.get_owned_session = AsyncMock(return_value=MagicMock(id="sess-1"))
    service.get_session_timeline = AsyncMock(
        return_value=(
            200,
            {
                "session_id": "sess-1",
                "events": [
                    {
                        "id": "evt-1",
                        "type": "BAR_CLOSED",
                        "payload": {"open": 100.0},
                        # The exact field that crashed send_json() -- a real
                        # datetime, not a pre-serialized string.
                        "created_at": datetime.now(timezone.utc),
                    }
                ],
            },
        )
    )
    return service


def test_ws_sends_valid_json_timeline_snapshot_with_datetime_events(monkeypatch) -> None:
    mock_service = _make_mock_service()

    async def _override():
        return mock_service

    app.dependency_overrides[get_strategy_service] = _override

    monkeypatch.setattr(
        "app.modules.user_service.utils.auth_utils.JWTUtils.decode_access_token",
        lambda token: {"sub": "user-1"},
    )

    try:
        client = TestClient(app)
        with client.websocket_connect(
            "/api/v1/live-sessions/sess-1/ws?token=fake-token"
        ) as websocket:
            # Would previously raise a WebSocketDisconnect here -- the server
            # crashed with TypeError before ever sending a byte.
            raw = websocket.receive_text()
            message = json.loads(raw)

        assert message["type"] == "TIMELINE_SNAPSHOT"
        assert message["data"]["events"][0]["type"] == "BAR_CLOSED"
        assert isinstance(message["data"]["events"][0]["created_at"], str)
    finally:
        del app.dependency_overrides[get_strategy_service]
