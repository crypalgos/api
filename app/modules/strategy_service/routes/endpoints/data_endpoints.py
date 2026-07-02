import logging
from typing import Annotated
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.advices.base_response_handler import BaseResponseHandler
from app.advices.responses import SuccessResponseSchema
from app.middlewares.auth_middleware import get_current_user
from app.modules.strategy_service.schema.strategy_schema import (
    ResearchRunProgressResponseSchema,
    ResearchRunResponseSchema,
    EditResearchRunRequestSchema,
    FavoriteResearchRunRequestSchema,
)
from app.modules.strategy_service.routes.strategy_routes import (
    get_strategy_service,
    security,
)
from app.modules.strategy_service.services.strategy_service import StrategyService

logger = logging.getLogger(__name__)
data_router = APIRouter()


@data_router.get(
    "/research-runs/{run_id}",
    dependencies=[Depends(security)],
    responses={
        200: {"model": SuccessResponseSchema[ResearchRunResponseSchema]},
    },
)
async def get_research_run(
    strategy_id: str,
    run_id: str,
    user: Annotated[dict, Depends(get_current_user)],
    strategy_service: StrategyService = Depends(get_strategy_service),
) -> JSONResponse:
    """Fetch details of a single research run."""
    status_code, result = await strategy_service.get_run(
        user["user_id"], strategy_id=strategy_id, run_id=run_id
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@data_router.put(
    "/research-runs/{run_id}",
    dependencies=[Depends(security)],
    responses={
        200: {"model": SuccessResponseSchema[ResearchRunResponseSchema]},
    },
)
async def edit_research_run(
    run_id: str,
    payload: EditResearchRunRequestSchema,
    user: Annotated[dict, Depends(get_current_user)],
    strategy_service: StrategyService = Depends(get_strategy_service),
) -> JSONResponse:
    """Update metadata (name/description) of a research run."""
    status_code, result = await strategy_service.edit_run(
        user["user_id"],
        run_id=run_id,
        name=payload.name,
        description=payload.description,
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@data_router.put(
    "/research-runs/{run_id}/favorite",
    dependencies=[Depends(security)],
    responses={
        200: {"model": SuccessResponseSchema[ResearchRunResponseSchema]},
    },
)
async def favorite_research_run(
    run_id: str,
    payload: FavoriteResearchRunRequestSchema,
    user: Annotated[dict, Depends(get_current_user)],
    strategy_service: StrategyService = Depends(get_strategy_service),
) -> JSONResponse:
    """Toggle favorite status of a research run."""
    status_code, result = await strategy_service.toggle_run_favorite(
        user["user_id"], run_id=run_id, is_favorite=payload.is_favorite
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@data_router.delete(
    "/research-runs/{run_id}",
    dependencies=[Depends(security)],
)
async def delete_research_run(
    run_id: str,
    user: Annotated[dict, Depends(get_current_user)],
    strategy_service: StrategyService = Depends(get_strategy_service),
) -> JSONResponse:
    """Delete a research run and its storage files."""
    status_code, result = await strategy_service.delete_run(
        user["user_id"], run_id=run_id
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@data_router.get(
    "/research-runs/{run_id}/progress",
    dependencies=[Depends(security)],
    responses={
        200: {"model": SuccessResponseSchema[ResearchRunProgressResponseSchema]},
    },
)
async def get_research_run_progress(
    run_id: str,
    user: Annotated[dict, Depends(get_current_user)],
    strategy_service: StrategyService = Depends(get_strategy_service),
) -> JSONResponse:
    """Fetch real-time active task progress metrics."""
    status_code, result = await strategy_service.get_run_progress(
        user["user_id"], run_id
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@data_router.get(
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


@data_router.get(
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


@data_router.get(
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
