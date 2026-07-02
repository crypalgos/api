import logging
from typing import Annotated, Optional
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.advices.base_response_handler import BaseResponseHandler
from app.advices.responses import ErrorResponseSchema, SuccessResponseSchema
from app.middlewares.auth_middleware import get_current_user
from app.modules.strategy_service.schema.strategy_schema import (
    StrategyCreateSchema,
    StrategyResponseSchema,
    PaginatedStrategiesResponseSchema,
    UpdateCanvasRequestSchema,
    SaveCodeRequestSchema,
    TemplateLibraryItemSchema,
)
from app.modules.strategy_service.routes.strategy_routes import (
    get_strategy_service,
    security,
)
from app.modules.strategy_service.services.strategy_service import StrategyService

logger = logging.getLogger(__name__)
core_router = APIRouter()


@core_router.post(
    "/strategies",
    dependencies=[Depends(security)],
    responses={
        201: {"model": SuccessResponseSchema[StrategyResponseSchema]},
        401: {"model": ErrorResponseSchema},
    },
)
async def create_strategy(
    strategy_data: StrategyCreateSchema,
    user: Annotated[dict, Depends(get_current_user)],
    strategy_service: StrategyService = Depends(get_strategy_service),
) -> JSONResponse:
    """Create a new visual React Flow strategy canvas, auto-generating standard code base."""
    status_code, result = await strategy_service.create_strategy(
        user_id=user["user_id"],
        name=strategy_data.name,
        description=strategy_data.description,
        canvas_json=strategy_data.canvas_json,
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@core_router.get(
    "/strategies",
    dependencies=[Depends(security)],
    responses={
        200: {"model": SuccessResponseSchema[PaginatedStrategiesResponseSchema]},
        401: {"model": ErrorResponseSchema},
    },
)
async def list_strategies(
    user: Annotated[dict, Depends(get_current_user)],
    page: int = 1,
    limit: int = 8,
    search: str = "",
    is_template: Optional[bool] = None,
    archived: bool = False,
    strategy_service: StrategyService = Depends(get_strategy_service),
) -> JSONResponse:
    """List saved strategies belonging to the authenticated user with pagination, filtering, and search."""
    status_code, result = await strategy_service.list_strategies(
        user_id=user["user_id"],
        page=page,
        limit=limit,
        search=search,
        is_template=is_template,
        archived=archived,
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@core_router.get(
    "/strategies/{strategy_id}",
    dependencies=[Depends(security)],
    responses={
        200: {"model": SuccessResponseSchema[StrategyResponseSchema]},
        401: {"model": ErrorResponseSchema},
        404: {"model": ErrorResponseSchema},
    },
)
async def get_strategy(
    strategy_id: str,
    user: Annotated[dict, Depends(get_current_user)],
    strategy_service: StrategyService = Depends(get_strategy_service),
) -> JSONResponse:
    """Fetch a specific visual strategy canvas."""
    status_code, result = await strategy_service.get_strategy(
        user["user_id"], strategy_id
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@core_router.put(
    "/strategies/{strategy_id}/canvas",
    dependencies=[Depends(security)],
    responses={
        200: {"model": SuccessResponseSchema[StrategyResponseSchema]},
        401: {"model": ErrorResponseSchema},
        404: {"model": ErrorResponseSchema},
    },
)
async def update_canvas(
    strategy_id: str,
    canvas_data: UpdateCanvasRequestSchema,
    user: Annotated[dict, Depends(get_current_user)],
    strategy_service: StrategyService = Depends(get_strategy_service),
) -> JSONResponse:
    """Save the visual canvas node/edge graph and recompile it to Python strategy code."""
    status_code, result = await strategy_service.update_canvas(
        user_id=user["user_id"],
        strategy_id=strategy_id,
        canvas_json=canvas_data.canvas_json,
        name=canvas_data.name,
        description=canvas_data.description,
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@core_router.put(
    "/strategies/{strategy_id}/code",
    dependencies=[Depends(security)],
    responses={
        200: {"model": SuccessResponseSchema[dict]},
        401: {"model": ErrorResponseSchema},
        404: {"model": ErrorResponseSchema},
    },
)
async def save_monaco_code(
    strategy_id: str,
    code_data: SaveCodeRequestSchema,
    user: Annotated[dict, Depends(get_current_user)],
    strategy_service: StrategyService = Depends(get_strategy_service),
) -> JSONResponse:
    """Overwrite standard compiled code with custom user edits inside Monaco editor."""
    status_code, result = await strategy_service.save_custom_code(
        user_id=user["user_id"], strategy_id=strategy_id, code=code_data.code
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@core_router.post(
    "/strategies/{strategy_id}/reset-builder",
    dependencies=[Depends(security)],
    responses={
        200: {"model": SuccessResponseSchema[StrategyResponseSchema]},
        401: {"model": ErrorResponseSchema},
        404: {"model": ErrorResponseSchema},
    },
)
async def reset_builder(
    strategy_id: str,
    user: Annotated[dict, Depends(get_current_user)],
    strategy_service: StrategyService = Depends(get_strategy_service),
) -> JSONResponse:
    """Reset custom Monaco code changes and re-compile from visual canvas DAG layout."""
    status_code, result = await strategy_service.reset_to_visual_builder(
        user["user_id"], strategy_id
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@core_router.delete(
    "/strategies/{strategy_id}",
    dependencies=[Depends(security)],
    responses={
        200: {"model": SuccessResponseSchema[dict]},
        401: {"model": ErrorResponseSchema},
        404: {"model": ErrorResponseSchema},
    },
)
async def delete_strategy(
    strategy_id: str,
    user: Annotated[dict, Depends(get_current_user)],
    strategy_service: StrategyService = Depends(get_strategy_service),
) -> JSONResponse:
    """Archive a visual strategy canvas owned by the authenticated user."""
    status_code, result = await strategy_service.delete_strategy(
        user["user_id"], strategy_id
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@core_router.post(
    "/strategies/{strategy_id}/restore",
    dependencies=[Depends(security)],
    responses={
        200: {"model": SuccessResponseSchema[StrategyResponseSchema]},
        401: {"model": ErrorResponseSchema},
        404: {"model": ErrorResponseSchema},
    },
)
async def restore_strategy(
    strategy_id: str,
    user: Annotated[dict, Depends(get_current_user)],
    strategy_service: StrategyService = Depends(get_strategy_service),
) -> JSONResponse:
    """Restore/unarchive a strategy from soft delete."""
    status_code, result = await strategy_service.restore_strategy(
        user["user_id"], strategy_id
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@core_router.get(
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
