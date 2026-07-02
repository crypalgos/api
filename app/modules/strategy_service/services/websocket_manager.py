import logging
import json
from typing import Dict, List, Any
from fastapi import WebSocket

logger = logging.getLogger(__name__)


class WebsocketManager:
    def __init__(self):
        # Maps run_id -> list of active WebSockets
        self.active_connections: Dict[str, List[WebSocket]] = {}

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

        # Format event payload to JSON
        payload = {
            "event_type": event.__class__.__name__,
            "timestamp": getattr(event, "timestamp", 0),
            "symbol": getattr(event, "symbol_id", ""),
            "data": {
                k: (v.name if hasattr(v, "name") else v)
                for k, v in event.__dict__.items()
                if k != "context"
            },
        }

        message_str = json.dumps(payload)

        # Broadcast to all connected websockets for this run_id
        for connection in list(self.active_connections[run_id]):
            try:
                await connection.send_text(message_str)
            except Exception as e:
                logger.error(f"Error sending WebSocket message: {e}")
                self.disconnect(run_id, connection)


# Global singleton
websocket_manager = WebsocketManager()
