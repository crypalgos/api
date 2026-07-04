import logging
from typing import Annotated
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.advices.base_response_handler import BaseResponseHandler
from app.middlewares.auth_middleware import get_current_user
from app.modules.strategy_service.routes.strategy_routes import (
    get_strategy_service,
    security,
)
from app.modules.strategy_service.services.strategy_service import StrategyService

logger = logging.getLogger(__name__)
data_router = APIRouter()


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
    "/research-runs/{run_id}/datasets/{dataset_name:path}",
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
