import logging
from typing import Annotated, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.advices.base_response_handler import BaseResponseHandler
from app.advices.responses import ErrorResponseSchema, SuccessResponseSchema
from app.db.connect_db import get_db
from app.middlewares.auth_middleware import get_current_user
from app.modules.strategy_service.repositories.research_run_repository import (
    ResearchRunRepository,
)
from app.modules.strategy_service.repositories.strategy_repository import (
    StrategyRepository,
)
from app.modules.strategy_service.schema.strategy_schema import (
    BacktestTriggerRequestSchema,
    EditResearchRunRequestSchema,
    FavoriteResearchRunRequestSchema,
    MonteCarloRequestSchema,
    OptimizationRequestSchema,
    PaginatedResearchRunsResponseSchema,
    PaginatedStrategiesResponseSchema,
    ResearchNoteCreateSchema,
    ResearchNoteResponseSchema,
    ResearchRunProgressResponseSchema,
    ResearchRunResponseSchema,
    ResearchRunTriggerResponseSchema,
    SaveCodeRequestSchema,
    SaveVersionRequestSchema,
    StrategyCreateSchema,
    StrategyResponseSchema,
    StrategyVersionResponseSchema,
    TemplateLibraryItemSchema,
    UpdateCanvasRequestSchema,
    UpdateVersionApprovalRequestSchema,
    UpdateVersionLabelRequestSchema,
    VersionDiffResponseSchema,
    WalkForwardRequestSchema,
)
from app.modules.strategy_service.services.strategy_service import StrategyService

logger = logging.getLogger(__name__)

security = HTTPBearer()
strategy_router = APIRouter(tags=["Strategies"])


async def get_strategy_service(
    session: AsyncSession = Depends(get_db),
) -> StrategyService:
    return StrategyService(StrategyRepository(session), ResearchRunRepository(session))


from app.modules.strategy_service.routes.endpoints.core_endpoints import core_router
from app.modules.strategy_service.routes.endpoints.version_endpoints import (
    version_router,
)
from app.modules.strategy_service.routes.endpoints.job_endpoints import job_router
from app.modules.strategy_service.routes.endpoints.data_endpoints import data_router
from app.modules.strategy_service.routes.endpoints.live_endpoints import live_router

strategy_router.include_router(core_router)
strategy_router.include_router(version_router)
strategy_router.include_router(job_router)
strategy_router.include_router(data_router)
strategy_router.include_router(live_router)


# ─────────────────────────────────────────────────────────────────────────────
# General Run Operations (Rename, Favorites, Delete, Progress, Latest, Charting)
# ─────────────────────────────────────────────────────────────────────────────


@strategy_router.patch(
    "/research-runs/{run_id}",
    dependencies=[Depends(security)],
    responses={
        200: {"model": SuccessResponseSchema[ResearchRunResponseSchema]},
    },
)
async def rename_run(
    run_id: str,
    data: EditResearchRunRequestSchema,
    user: Annotated[dict, Depends(get_current_user)],
    strategy_service: StrategyService = Depends(get_strategy_service),
) -> JSONResponse:
    """Edit a run's name and/or description."""
    status_code, result = await strategy_service.edit_run(
        user_id=user["user_id"],
        run_id=run_id,
        name=data.name,
        description=data.description,
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@strategy_router.patch(
    "/research-runs/{run_id}/favorite",
    dependencies=[Depends(security)],
    responses={
        200: {"model": SuccessResponseSchema[ResearchRunResponseSchema]},
    },
)
async def favorite_run(
    run_id: str,
    data: FavoriteResearchRunRequestSchema,
    user: Annotated[dict, Depends(get_current_user)],
    strategy_service: StrategyService = Depends(get_strategy_service),
) -> JSONResponse:
    """Toggle favorite status of a run."""
    status_code, result = await strategy_service.toggle_run_favorite(
        user_id=user["user_id"], run_id=run_id, is_favorite=data.is_favorite
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@strategy_router.delete(
    "/research-runs/{run_id}",
    dependencies=[Depends(security)],
)
async def delete_run(
    run_id: str,
    user: Annotated[dict, Depends(get_current_user)],
    strategy_service: StrategyService = Depends(get_strategy_service),
) -> JSONResponse:
    """Delete a run from PostgreSQL database and clear its compressed msgpack payloads from storage."""
    status_code, result = await strategy_service.delete_run(user["user_id"], run_id)
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@strategy_router.get(
    "/research-runs/{run_id}/progress",
    dependencies=[Depends(security)],
    responses={
        200: {"model": SuccessResponseSchema[ResearchRunProgressResponseSchema]},
    },
)
async def get_run_progress(
    run_id: str,
    user: Annotated[dict, Depends(get_current_user)],
    strategy_service: StrategyService = Depends(get_strategy_service),
) -> JSONResponse:
    """Fetch real-time active task progress metrics."""
    status_code, result = await strategy_service.get_run_progress(
        user["user_id"], run_id
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@strategy_router.get(
    "/strategies/{strategy_id}/latest/{run_type}",
    dependencies=[Depends(security)],
)
async def get_latest_run(
    strategy_id: str,
    run_type: str,
    user: Annotated[dict, Depends(get_current_user)],
    strategy_service: StrategyService = Depends(get_strategy_service),
) -> JSONResponse:
    """Load latest run results directly from latest/ object folder in S3."""
    status_code, result = await strategy_service.get_latest_run(
        user["user_id"], strategy_id=strategy_id, run_type=run_type
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@strategy_router.get(
    "/templates",
    dependencies=[Depends(security)],
    responses={
        200: {"model": SuccessResponseSchema[list[TemplateLibraryItemSchema]]},
    },
)
async def get_templates(
    user: Annotated[dict, Depends(get_current_user)],
    strategy_service: StrategyService = Depends(get_strategy_service),
) -> JSONResponse:
    """Fetch strategy templates library with pre-loaded latest results mapping summaries (no S3 scanning)."""
    status_code, result = await strategy_service.get_template_library(user["user_id"])
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@strategy_router.get(
    "/research-runs/{run_id}/datasets/{dataset_name}",
    dependencies=[Depends(security)],
)
async def get_run_dataset_chart(
    run_id: str,
    dataset_name: str,
    user: Annotated[dict, Depends(get_current_user)],
    strategy_service: StrategyService = Depends(get_strategy_service),
) -> JSONResponse:
    """Download the heavy dataset payload from storage and extract specific chart curves."""
    status_code, result = await strategy_service.get_run_dataset_chart(
        user["user_id"], run_id=run_id, dataset_name=dataset_name
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@strategy_router.get(
    "/research-runs/{run_id}/artifacts/{artifact_type}",
    dependencies=[Depends(security)],
)
async def get_run_artifact(
    run_id: str,
    artifact_type: str,
    user: Annotated[dict, Depends(get_current_user)],
    strategy_service: StrategyService = Depends(get_strategy_service),
) -> JSONResponse:
    """Download a specific artifact for a run."""
    status_code, result = await strategy_service.get_run_artifact(
        user["user_id"], run_id=run_id, artifact_type=artifact_type
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


from app.modules.strategy_service.services.strategy_manager import strategy_manager
from crypalgos_core.engine.context import ExecutionMode
from pydantic import BaseModel


class DeployRequest(BaseModel):
    run_id: str
    mode: str = "PAPER"
    initial_capital: float = 10000.0
    leverage: int = 1


@strategy_router.post(
    "/{strategy_id}/deploy",
    dependencies=[Depends(security)],
)
async def deploy_strategy(
    strategy_id: str,
    payload: DeployRequest,
    user: Annotated[dict, Depends(get_current_user)],
) -> JSONResponse:
    """Deploy a strategy class dynamically in PAPER or LIVE mode."""
    mode_enum = ExecutionMode[payload.mode.upper()]
    await strategy_manager.deploy(
        strategy_id=strategy_id,
        run_id=payload.run_id,
        user_id=user["user_id"],
        mode=mode_enum,
        initial_capital=payload.initial_capital,
        leverage=payload.leverage,
    )
    return BaseResponseHandler.success_response(
        data={"message": "Strategy deployed successfully"}, status_code=200
    )


@strategy_router.post(
    "/runs/{run_id}/stop",
    dependencies=[Depends(security)],
)
async def stop_run(
    run_id: str, user: Annotated[dict, Depends(get_current_user)]
) -> JSONResponse:
    """Stop a running strategy runner."""
    await strategy_manager.stop(run_id)
    return BaseResponseHandler.success_response(
        data={"message": "Strategy runner stopped successfully"}, status_code=200
    )


@strategy_router.get(
    "/runs/{run_id}/status",
    dependencies=[Depends(security)],
)
async def get_run_status(
    run_id: str, user: Annotated[dict, Depends(get_current_user)]
) -> JSONResponse:
    """Get the running status and latest metrics of an active strategy runner."""
    status = strategy_manager.get_status(run_id)
    return BaseResponseHandler.success_response(data=status, status_code=200)


from fastapi import WebSocket, WebSocketDisconnect
from app.modules.strategy_service.services.websocket_manager import websocket_manager


@strategy_router.websocket("/runs/{run_id}/ws")
async def strategy_run_websocket(websocket: WebSocket, run_id: str):
    """Exposes real-time event updates stream for a running strategy session."""
    await websocket_manager.connect(run_id, websocket)
    try:
        while True:
            # Keep connection alive, listen for any client messages
            await websocket.receive_text()
    except WebSocketDisconnect:
        websocket_manager.disconnect(run_id, websocket)
    except Exception as e:
        logger.error(f"WebSocket session error: {e}")
        websocket_manager.disconnect(run_id, websocket)
