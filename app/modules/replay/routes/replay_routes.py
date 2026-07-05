import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.advices.base_response_handler import BaseResponseHandler
from app.db.connect_db import get_db
from app.middlewares.auth_middleware import get_current_user
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


# ── Session bootstrap ───────────────────────────────────────────────────────

@replay_router.get(
    "/research-runs/{run_id}/replay/session",
    dependencies=[Depends(security)],
)
async def get_replay_session(
    run_id: str,
    user: Annotated[dict, Depends(get_current_user)],
    replay_service: ReplayService = Depends(get_replay_service),
) -> JSONResponse:
    """Replay session metadata: validated manifest, symbols, timeline markers."""
    result = await replay_service.get_session(user["user_id"], run_id)
    return BaseResponseHandler.success_response(data=result, status_code=200)


# ── Windowed replay (pre-nested trees — frontend reconstructs nothing) ─────

@replay_router.get(
    "/research-runs/{run_id}/replay/window",
    dependencies=[Depends(security)],
)
async def get_replay_window(
    run_id: str,
    user: Annotated[dict, Depends(get_current_user)],
    from_candle: int = Query(0, ge=0),
    to_candle: int = Query(100, ge=0),
    replay_service: ReplayService = Depends(get_replay_service),
) -> JSONResponse:
    """One replay window: candles + nested event trees + traces + indicators."""
    result = await replay_service.get_window(
        user["user_id"], run_id, from_candle, to_candle
    )
    return BaseResponseHandler.success_response(data=result, status_code=200)


# ── Trade inspector ─────────────────────────────────────────────────────────

@replay_router.get(
    "/research-runs/{run_id}/replay/trades/{trade_id}",
    dependencies=[Depends(security)],
)
async def get_replay_trade(
    run_id: str,
    trade_id: str,
    user: Annotated[dict, Depends(get_current_user)],
    replay_service: ReplayService = Depends(get_replay_service),
) -> JSONResponse:
    """Everything about one trade: lifecycle events + entry/exit decision trees."""
    result = await replay_service.get_trade(user["user_id"], run_id, trade_id)
    return BaseResponseHandler.success_response(data=result, status_code=200)


# ── Single dataset (allowlisted; also serves the legacy per-dataset paths) ──

@replay_router.get(
    "/research-runs/{run_id}/replay/datasets/{dataset_name}",
    dependencies=[Depends(security)],
)
async def get_replay_dataset(
    run_id: str,
    dataset_name: str,
    user: Annotated[dict, Depends(get_current_user)],
    start_bar: int = Query(0, ge=0),
    end_bar: int = Query(100, ge=0),
    replay_service: ReplayService = Depends(get_replay_service),
) -> JSONResponse:
    """Windowed slice of a single allowlisted replay dataset."""
    status_code, result = await replay_service.get_dataset_window(
        user["user_id"], run_id, dataset_name,
        start_bar=start_bar, end_bar=end_bar,
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


# ── Legacy aliases (deprecated — kept until the frontend migrates) ─────────

@replay_router.get(
    "/research-runs/{run_id}/replay/manifest",
    dependencies=[Depends(security)],
    deprecated=True,
)
async def get_replay_manifest(
    run_id: str,
    user: Annotated[dict, Depends(get_current_user)],
    replay_service: ReplayService = Depends(get_replay_service),
) -> JSONResponse:
    """Deprecated: use /replay/session."""
    status_code, result = await replay_service.get_manifest(user["user_id"], run_id)
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


def _register_legacy_dataset_route(path_name: str, dataset_name: str) -> None:
    @replay_router.get(
        f"/research-runs/{{run_id}}/replay/{path_name}",
        dependencies=[Depends(security)],
        deprecated=True,
        name=f"legacy_replay_{dataset_name}",
    )
    async def legacy_dataset(
        run_id: str,
        user: Annotated[dict, Depends(get_current_user)],
        start_bar: int = Query(0, ge=0),
        end_bar: int = Query(100, ge=0),
        replay_service: ReplayService = Depends(get_replay_service),
    ) -> JSONResponse:
        status_code, result = await replay_service.get_dataset_window(
            user["user_id"], run_id, dataset_name,
            start_bar=start_bar, end_bar=end_bar,
        )
        return BaseResponseHandler.success_response(data=result, status_code=status_code)


for _path, _dataset in (
    ("candles", "candles"),
    ("indicator-snapshots", "indicator_snapshots"),
    ("runtime-events", "runtime_events"),
    ("decision-traces", "decision_traces"),
):
    _register_legacy_dataset_route(_path, _dataset)
