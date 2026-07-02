import logging
from typing import Annotated, Generator
from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer

from app.advices.base_response_handler import BaseResponseHandler
from app.db.connect_db import get_db
from app.middlewares.auth_middleware import get_current_user
from app.modules.strategy_service.repositories.strategy_repository import (
    StrategyRepository,
)
from app.modules.strategy_service.repositories.research_run_repository import (
    ResearchRunRepository,
)
from app.modules.replay.services.replay_service import ReplayService

logger = logging.getLogger(__name__)
replay_router = APIRouter(tags=["Replay"])
security = HTTPBearer()


def get_replay_service(session: Annotated[Generator, Depends(get_db)]) -> ReplayService:
    return ReplayService(StrategyRepository(session), ResearchRunRepository(session))


@replay_router.get(
    "/research-runs/{run_id}/replay/manifest",
    dependencies=[Depends(security)],
)
async def get_replay_manifest(
    run_id: str,
    user: Annotated[dict, Depends(get_current_user)],
    replay_service: ReplayService = Depends(get_replay_service),
) -> JSONResponse:
    """Get metadata manifest for windowed replay (bar count, version, datasets)."""
    status_code, result = await replay_service.get_manifest(user["user_id"], run_id)
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@replay_router.get(
    "/research-runs/{run_id}/replay/candles",
    dependencies=[Depends(security)],
)
async def get_replay_candles(
    run_id: str,
    user: Annotated[dict, Depends(get_current_user)],
    start_bar: int = Query(0),
    end_bar: int = Query(100),
    replay_service: ReplayService = Depends(get_replay_service),
) -> JSONResponse:
    """Get windowed slice of candles/OHLCV data for replay."""
    status_code, result = await replay_service.get_dataset_window(
        user["user_id"],
        run_id,
        "candles",
        start_bar=start_bar,
        end_bar=end_bar,
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@replay_router.get(
    "/research-runs/{run_id}/replay/indicator-snapshots",
    dependencies=[Depends(security)],
)
async def get_replay_indicator_snapshots(
    run_id: str,
    user: Annotated[dict, Depends(get_current_user)],
    start_bar: int = Query(0),
    end_bar: int = Query(100),
    replay_service: ReplayService = Depends(get_replay_service),
) -> JSONResponse:
    """Get windowed slice of indicator snapshots for replay."""
    status_code, result = await replay_service.get_dataset_window(
        user["user_id"],
        run_id,
        "indicator_snapshots",
        start_bar=start_bar,
        end_bar=end_bar,
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@replay_router.get(
    "/research-runs/{run_id}/replay/runtime-events",
    dependencies=[Depends(security)],
)
async def get_replay_runtime_events(
    run_id: str,
    user: Annotated[dict, Depends(get_current_user)],
    start_bar: int = Query(0),
    end_bar: int = Query(100),
    replay_service: ReplayService = Depends(get_replay_service),
) -> JSONResponse:
    """Get windowed slice of execution runtime events ledger."""
    status_code, result = await replay_service.get_dataset_window(
        user["user_id"],
        run_id,
        "runtime_events",
        start_bar=start_bar,
        end_bar=end_bar,
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@replay_router.get(
    "/research-runs/{run_id}/replay/decision-traces",
    dependencies=[Depends(security)],
)
async def get_replay_decision_traces(
    run_id: str,
    user: Annotated[dict, Depends(get_current_user)],
    start_bar: int = Query(0),
    end_bar: int = Query(100),
    replay_service: ReplayService = Depends(get_replay_service),
) -> JSONResponse:
    """Get windowed slice of decision explanation traces."""
    status_code, result = await replay_service.get_dataset_window(
        user["user_id"],
        run_id,
        "decision_traces",
        start_bar=start_bar,
        end_bar=end_bar,
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)
