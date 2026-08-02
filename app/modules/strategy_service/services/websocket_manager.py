import json
import logging
from typing import Any, Dict, List

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class WebsocketManager:
    def __init__(self):
        # Maps run_id -> list of active WebSockets
        self.active_connections: Dict[str, List[WebSocket]] = {}
        # Second, separate registry for live-session connections (Phase 3) —
        # a different id space (LiveTradingSession.id, not a backtest run_id)
        # feeding off Redis-forwarded events rather than a local EngineEvent
        # object, so it gets its own connect/disconnect/broadcast trio rather
        # than overloading the run_id-keyed one above.
        self.session_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, run_id: str, websocket: WebSocket):
        await websocket.accept()
        if run_id not in self.active_connections:
            self.active_connections[run_id] = []
        self.active_connections[run_id].append(websocket)
        logger.info(f"WebSocket client connected to strategy run {run_id}")

    def disconnect(self, run_id: str, websocket: WebSocket):
        if run_id in self.active_connections:
            if websocket in self.active_connections[run_id]:
                self.active_connections[run_id].remove(websocket)
            if not self.active_connections[run_id]:
                del self.active_connections[run_id]
        logger.info(f"WebSocket client disconnected from strategy run {run_id}")

    async def broadcast(self, run_id: str, event: Any):
        if run_id not in self.active_connections:
            return

        # event.to_dict() is EngineEvent's own supported serialization —
        # event.__dict__ (the previous approach) raises AttributeError on
        # every call, since EngineEvent subclasses are
        # @dataclass(slots=True, ...) and have no instance __dict__ at all.
        # That exception was silently swallowed by the caller's unawaited
        # asyncio.create_task (ExecutionRunner.__init__'s handle_ws_broadcast),
        # so this broadcast path has never actually sent a real event.
        d = event.to_dict()
        payload = {
            "event_type": d["type"],
            "timestamp": getattr(event, "timestamp", 0),
            "symbol": getattr(event, "symbol_id", ""),
            "data": d["payload"],
        }

        message_str = json.dumps(payload, default=str)

        # Broadcast to all connected websockets for this run_id
        for connection in list(self.active_connections[run_id]):
            try:
                await connection.send_text(message_str)
            except Exception as e:
                logger.error(f"Error sending WebSocket message: {e}")
                self.disconnect(run_id, connection)

    async def connect_session(self, session_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self.session_connections.setdefault(session_id, []).append(websocket)
        logger.info(f"WebSocket client connected to live session {session_id}")

    def disconnect_session(self, session_id: str, websocket: WebSocket) -> None:
        conns = self.session_connections.get(session_id)
        if not conns:
            return
        if websocket in conns:
            conns.remove(websocket)
        if not conns:
            del self.session_connections[session_id]
        logger.info(f"WebSocket client disconnected from live session {session_id}")

    async def broadcast_to_session(self, session_id: str, message: str) -> None:
        """message is already-serialized JSON — forwarded verbatim from the
        Redis "live-session:*" channel (see live_event_bridge.py), which is
        itself EventPublisher.broadcast()'s json.dumps(event.to_dict())."""
        conns = self.session_connections.get(session_id)
        if not conns:
            return
        for connection in list(conns):
            try:
                await connection.send_text(message)
            except Exception as e:
                logger.error(f"Error sending session WebSocket message: {e}")
                self.disconnect_session(session_id, connection)


# Global singleton
websocket_manager = WebsocketManager()
