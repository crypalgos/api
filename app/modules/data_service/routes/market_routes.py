import json
import logging
import asyncio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from fastapi.responses import JSONResponse
from decimal import Decimal
from typing import Dict, Set
from app.advices.base_response_handler import BaseResponseHandler
from app.modules.data_service.services.orderbook_projection import orderbook_registry, OrderBookSnapshot
from app.modules.data_service.live_feed import live_feed_subscriber

logger = logging.getLogger(__name__)

market_router = APIRouter(prefix="/market", tags=["Market Data & Projections"])

class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)

class OrderBookWSManager:
    def __init__(self):
        # symbol -> set of connected websockets
        self.active_connections: Dict[str, Set[WebSocket]] = {}
        # symbol -> background ZMQ listener task
        self.listener_tasks: Dict[str, asyncio.Task] = {}

    async def connect(self, symbol: str, websocket: WebSocket):
        await websocket.accept()
        if symbol not in self.active_connections:
            self.active_connections[symbol] = set()
            # Start background ZMQ subscriber task for this symbol
            self.listener_tasks[symbol] = asyncio.create_task(self._subscribe_zmq_feed(symbol))
        
        self.active_connections[symbol].add(websocket)
        logger.info(f"Client connected to order book feed for {symbol}. Total: {len(self.active_connections[symbol])}")

        # Send initial snapshot immediately
        proj = orderbook_registry.get_projection("delta", symbol)
        snap = proj.get_snapshot(depth=20)
        await websocket.send_text(self._serialize_snapshot(snap))

    def disconnect(self, symbol: str, websocket: WebSocket):
        if symbol in self.active_connections:
            self.active_connections[symbol].discard(websocket)
            logger.info(f"Client disconnected from order book feed for {symbol}. Remaining: {len(self.active_connections[symbol])}")
            
            if not self.active_connections[symbol]:
                # Clean up subscriber if no clients are listening
                task = self.listener_tasks.pop(symbol, None)
                if task:
                    task.cancel()
                self.active_connections.pop(symbol, None)

    async def broadcast(self, symbol: str, snapshot: OrderBookSnapshot):
        if symbol not in self.active_connections:
            return
            
        payload = self._serialize_snapshot(snapshot)
        for ws in list(self.active_connections[symbol]):
            try:
                await ws.send_text(payload)
            except Exception:
                self.disconnect(symbol, ws)

    def _serialize_snapshot(self, snap: OrderBookSnapshot) -> str:
        return json.dumps({
            "instrument": snap.instrument.to_dict(),
            "sequence": snap.sequence,
            "exchange_timestamp": snap.exchange_timestamp,
            "received_at": snap.received_at,
            "status": snap.status.value,
            "schema_version": snap.schema_version,
            "bids": [[str(lvl.price), str(lvl.size)] for lvl in snap.bids],
            "asks": [[str(lvl.price), str(lvl.size)] for lvl in snap.asks]
        })

    async def _subscribe_zmq_feed(self, symbol: str):
        """Worker task subscribing once to ZMQ l2_updates and pushing to active connections."""
        logger.info(f"Starting order book ZMQ subscription task for {symbol}")
        
        # We hook into live_feed_subscriber ZMQ events
        proj = orderbook_registry.get_projection("delta", symbol)
        
        queue = asyncio.Queue()
        
        # Callback to route ZMQ messages to our queue
        async def on_feed_update(topic: str, data: dict):
            # Parse only l2_updates for this symbol
            if topic == f"l2_updates.delta" and data.get("symbol") == symbol:
                await queue.put(data)

        live_feed_subscriber.register_callback(on_feed_update)
        
        try:
            while True:
                data = await queue.get()
                
                # Apply increment deltas to the projection
                changed = proj.apply_update(
                    bids_delta=data.get("bids", []),
                    asks_delta=data.get("asks", []),
                    sequence=data.get("sequence", 0),
                    timestamp=data.get("timestamp", 0)
                )
                
                # Only broadcast to WebSocket clients if bids/asks top levels changed
                if changed:
                    snap = proj.get_snapshot(depth=20)
                    await self.broadcast(symbol, snap)
                    
        except asyncio.CancelledError:
            logger.info(f"Cancelled ZMQ subscription task for {symbol}")
        finally:
            live_feed_subscriber.unregister_callback(on_feed_update)

ws_manager = OrderBookWSManager()

@market_router.get("/orderbook/{symbol}")
async def get_orderbook_snapshot(
    symbol: str,
    depth: int = Query(20, enum=[10, 20, 50])
) -> JSONResponse:
    proj = orderbook_registry.get_projection("delta", symbol)
    snap = proj.get_snapshot(depth=depth)
    return BaseResponseHandler.success_response(
        data={
            "instrument": snap.instrument.to_dict(),
            "sequence": snap.sequence,
            "exchange_timestamp": snap.exchange_timestamp,
            "received_at": snap.received_at,
            "status": snap.status.value,
            "schema_version": snap.schema_version,
            "bids": [[str(lvl.price), str(lvl.size)] for lvl in snap.bids],
            "asks": [[str(lvl.price), str(lvl.size)] for lvl in snap.asks]
        },
        status_code=200
    )

@market_router.websocket("/orderbook/{symbol}/ws")
async def orderbook_websocket(websocket: WebSocket, symbol: str):
    await ws_manager.connect(symbol, websocket)
    try:
        while True:
            # Keep connection alive
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(symbol, websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        ws_manager.disconnect(symbol, websocket)
