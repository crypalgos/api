import logging
from typing import Annotated
from fastapi import APIRouter, Depends, Body
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer

from app.advices.base_response_handler import BaseResponseHandler
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
    strategy_service: StrategyService = Depends(get_strategy_service),
) -> JSONResponse:
    """Start a new Live or Paper trading session for a strategy."""
    status_code, result = await strategy_service.start_live_session(
        user.user_id,
        strategy_id=strategy_id,
        mode=mode,
        broker=broker,
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
