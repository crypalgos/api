import json
import logging
from datetime import datetime
from typing import Annotated, Optional

from fastapi import APIRouter, Body, Depends, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from app.advices.base_response_handler import BaseResponseHandler
from app.exceptions.exceptions import ResourceNotFoundException
from app.middlewares.auth_middleware import CurrentUser, get_current_user
from app.modules.strategy_service.routes.strategy_routes import (
    get_strategy_service,
    security,
)
from app.modules.strategy_service.services.strategy_service import StrategyService

logger = logging.getLogger(__name__)
live_router = APIRouter()


@live_router.post(
    "/strategies/{strategy_id}/live-sessions",
    dependencies=[Depends(security)],
)
async def start_live_session(
    strategy_id: str,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    mode: str = Body(..., description="LIVE or PAPER"),
    broker: str = Body(default="paper", description="delta or paper"),
    credential_id: Optional[str] = Body(
        default=None, description="Required for PAPER (Testnet) and LIVE (Production)"
    ),
    strategy_service: StrategyService = Depends(get_strategy_service),
) -> JSONResponse:
    """Start a new Live or Paper trading session for a strategy."""
    status_code, result = await strategy_service.start_live_session(
        user.user_id,
        strategy_id=strategy_id,
        mode=mode,
        broker=broker,
        credential_id=credential_id,
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@live_router.delete(
    "/strategies/{strategy_id}/live-sessions/{session_id}",
    dependencies=[Depends(security)],
)
async def stop_live_session(
    strategy_id: str,
    session_id: str,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    strategy_service: StrategyService = Depends(get_strategy_service),
) -> JSONResponse:
    """Stop an active Live or Paper trading session."""
    status_code, result = await strategy_service.stop_live_session(
        user.user_id,
        strategy_id=strategy_id,
        session_id=session_id,
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@live_router.get(
    "/strategies/{strategy_id}/live-sessions/{session_id}",
    dependencies=[Depends(security)],
)
async def get_live_session(
    strategy_id: str,
    session_id: str,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    strategy_service: StrategyService = Depends(get_strategy_service),
) -> JSONResponse:
    """Get details and current status of a live trading session."""
    status_code, result = await strategy_service.get_live_session(
        user.user_id,
        strategy_id=strategy_id,
        session_id=session_id,
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@live_router.get(
    "/strategies/{strategy_id}/live-sessions",
    dependencies=[Depends(security)],
)
async def list_live_sessions(
    strategy_id: str,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    strategy_service: StrategyService = Depends(get_strategy_service),
) -> JSONResponse:
    """List all Live/Paper trading sessions for a strategy."""
    status_code, result = await strategy_service.list_live_sessions(
        user.user_id,
        strategy_id=strategy_id,
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


# ─────────────────────────────────────────────────────────────────────────
# Flat routes — session ids are already globally unique, and the fleet page
# (Phase 4) wants to address sessions across strategies without a strategy_id
# in the URL. Deliberately not nested under /strategies/{strategy_id}/... like
# the CRUD routes above.
# ─────────────────────────────────────────────────────────────────────────


@live_router.get(
    "/live-sessions",
    dependencies=[Depends(security)],
)
async def list_all_live_sessions(
    user: Annotated[CurrentUser, Depends(get_current_user)],
    status: Optional[str] = Query(default=None),
    mode: Optional[str] = Query(default=None),
    strategy_service: StrategyService = Depends(get_strategy_service),
) -> JSONResponse:
    """Cross-strategy Live/Paper session list — the fleet page's data source."""
    status_code, result = await strategy_service.list_all_live_sessions(
        user.user_id, status=status, mode=mode
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@live_router.get(
    "/live-sessions/{session_id}/timeline",
    dependencies=[Depends(security)],
)
async def get_live_session_timeline(
    session_id: str,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    since: Optional[datetime] = Query(
        default=None, description="Only events created after this timestamp"
    ),
    limit: int = Query(default=2500, le=2500),
    strategy_service: StrategyService = Depends(get_strategy_service),
) -> JSONResponse:
    """REST scrollback over strategy_events for one session — used both by the
    WS handler internally on connect and directly by the frontend on reconnect."""
    status_code, result = await strategy_service.get_session_timeline(
        user.user_id, session_id=session_id, since=since, limit=limit
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@live_router.get(
    "/live-sessions/{session_id}/replay",
    dependencies=[Depends(security)],
)
async def get_live_session_replay(
    session_id: str,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    strategy_service: StrategyService = Depends(get_strategy_service),
) -> JSONResponse:
    """Environment-resolved deterministic replay for one live session."""
    status_code, result = await strategy_service.get_session_replay(
        user.user_id, session_id
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@live_router.websocket("/live-sessions/{session_id}/ws")
async def live_session_ws(
    websocket: WebSocket,
    session_id: str,
    token: Optional[str] = Query(default=None),
    strategy_service: StrategyService = Depends(get_strategy_service),
) -> None:
    """Authenticated live event stream for one session. Browsers can't set
    custom headers on a WebSocket handshake, and the app's auth token is
    already a plain client-readable cookie manually re-attached as a Bearer
    header for REST calls (see axios-interceptor.ts) — so the token travels
    as a `?token=` query param here instead, verified the same way
    get_current_user() verifies it for REST routes.

    On connect: hydrate from get_session_timeline(), then stay attached to
    the live Redis-fed tail (websocket_manager.broadcast_to_session, fed by
    live_event_bridge.py's psubscribe on "live-session:*").
    """
    from app.modules.strategy_service.services.websocket_manager import (
        websocket_manager,
    )
    from app.modules.user_service.utils.auth_utils import JWTUtils

    payload = JWTUtils.decode_access_token(token) if token else None
    user_id = payload.get("sub") if payload else None
    if not user_id:
        await websocket.close(code=4401)
        return

    try:
        await strategy_service.get_owned_session(user_id, session_id)
    except ResourceNotFoundException:
        await websocket.close(code=4404)
        return

    await websocket_manager.connect_session(session_id, websocket)
    try:
        _, timeline = await strategy_service.get_session_timeline(
            user_id, session_id=session_id
        )
        # WebSocket.send_json() calls plain json.dumps() with no `default=`
        # -- every event's `created_at` is a real datetime, so this crashed
        # unconditionally on the very first message of every connection
        # (TypeError: Object of type datetime is not JSON serializable),
        # closing the socket immediately and looping forever on the
        # frontend's reconnect logic. Same default=str convention
        # EventPublisher.broadcast() already uses for the exact same reason.
        await websocket.send_text(
            json.dumps({"type": "TIMELINE_SNAPSHOT", "data": timeline}, default=str)
        )

        while True:
            # No client->server messages expected; this just keeps the
            # connection open and detects disconnects.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        websocket_manager.disconnect_session(session_id, websocket)
