import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.advices.base_response_handler import BaseResponseHandler
from app.db.connect_db import get_db
from app.middlewares.auth_middleware import CurrentUser, get_current_user
from app.modules.replay.services.replay_service import ReplayService
from app.modules.strategy_service.repositories.research_run_repository import (
    ResearchRunRepository,
)
from app.modules.strategy_service.repositories.strategy_repository import (
    StrategyRepository,
)

logger = logging.getLogger(__name__)
replay_router = APIRouter(tags=["Replay"])
security = HTTPBearer()


def get_replay_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ReplayService:
    return ReplayService(StrategyRepository(session), ResearchRunRepository(session))


@replay_router.get(
    "/research-runs/{run_id}/replay/session",
    dependencies=[Depends(security)],
)
async def get_replay_session(
    run_id: str,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    replay_service: ReplayService = Depends(get_replay_service),
) -> JSONResponse:
    """Replay session metadata: validated manifest, symbols, timeline markers."""
    result = await replay_service.get_session(user.user_id, run_id)
    return BaseResponseHandler.success_response(data=result, status_code=200)


@replay_router.get(
    "/research-runs/{run_id}/replay/trades/{trade_id}",
    dependencies=[Depends(security)],
)
async def get_replay_trade(
    run_id: str,
    trade_id: str,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    replay_service: ReplayService = Depends(get_replay_service),
) -> JSONResponse:
    """Everything about one trade: lifecycle events + entry/exit decision trees."""
    result = await replay_service.get_trade(user.user_id, run_id, trade_id)
    return BaseResponseHandler.success_response(data=result, status_code=200)


@replay_router.get(
    "/research-runs/{run_id}/replay/datasets/{dataset_name}",
    dependencies=[Depends(security)],
)
async def get_replay_dataset(
    run_id: str,
    dataset_name: str,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    start_bar: int = Query(0, ge=0),
    end_bar: int = Query(100, ge=0),
    replay_service: ReplayService = Depends(get_replay_service),
) -> JSONResponse:
    """Windowed slice of a single allowlisted replay dataset (lazy panels)."""
    status_code, result = await replay_service.get_dataset_window(
        user.user_id, run_id, dataset_name,
        start_bar=start_bar, end_bar=end_bar,
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


# Immutable — a chunk's bytes for a given (run_id, dataset_name, chunk_id)
# never change once the run has completed, so it's safe to cache forever,
# both in the browser's HTTP cache and any CDN in front of this API.
_IMMUTABLE_CACHE_HEADERS = {"Cache-Control": "public, max-age=31536000, immutable"}


@replay_router.get(
    "/research-runs/{run_id}/replay/chunks/{dataset_name}/{chunk_id}",
    dependencies=[Depends(security)],
)
async def get_replay_chunk(
    run_id: str,
    dataset_name: str,
    chunk_id: int,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    replay_service: ReplayService = Depends(get_replay_service),
) -> Response:
    """One Arrow-IPC chunk of a single allowlisted dataset — binary,
    immutable, browser-cacheable. The replay engine's primary data path."""
    payload = await replay_service.get_dataset_chunk(user.user_id, run_id, dataset_name, chunk_id)
    return Response(
        content=payload,
        media_type="application/vnd.apache.arrow.stream",
        headers=_IMMUTABLE_CACHE_HEADERS,
    )


@replay_router.get(
    "/research-runs/{run_id}/replay/chunks/{chunk_id}/manifest",
    dependencies=[Depends(security)],
)
async def get_replay_chunk_manifest(
    run_id: str,
    chunk_id: int,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    replay_service: ReplayService = Depends(get_replay_service),
) -> JSONResponse:
    """Row counts + checksum for one chunk, across every allowlisted dataset —
    lets the client decide what to fetch without pulling each binary blind."""
    result = await replay_service.get_chunk_manifest(user.user_id, run_id, chunk_id)
    response = BaseResponseHandler.success_response(data=result, status_code=200)
    response.headers.update(_IMMUTABLE_CACHE_HEADERS)
    return response
