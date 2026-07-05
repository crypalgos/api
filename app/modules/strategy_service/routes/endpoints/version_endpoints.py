import logging
from typing import Annotated
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.advices.base_response_handler import BaseResponseHandler
from app.advices.responses import ErrorResponseSchema, SuccessResponseSchema
from app.middlewares.auth_middleware import CurrentUser, get_current_user
from app.modules.strategy_service.schema.strategy_schema import (
    SaveVersionRequestSchema,
    StrategyVersionResponseSchema,
    StrategyResponseSchema,
    VersionDiffResponseSchema,
    UpdateVersionLabelRequestSchema,
    UpdateVersionApprovalRequestSchema,
    ResearchNoteResponseSchema,
    ResearchNoteCreateSchema,
)
from app.modules.strategy_service.routes.strategy_routes import (
    get_strategy_service,
    security,
)
from app.modules.strategy_service.services.strategy_service import StrategyService

logger = logging.getLogger(__name__)
version_router = APIRouter()


@version_router.post(
    "/strategies/{strategy_id}/versions",
    dependencies=[Depends(security)],
    responses={
        201: {"model": SuccessResponseSchema[StrategyVersionResponseSchema]},
        401: {"model": ErrorResponseSchema},
        404: {"model": ErrorResponseSchema},
    },
)
async def save_strategy_version(
    strategy_id: str,
    payload: SaveVersionRequestSchema,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    strategy_service: StrategyService = Depends(get_strategy_service),
) -> JSONResponse:
    """Manually save a snapshot version of the strategy draft."""
    status_code, result = await strategy_service.save_version(
        user.user_id, strategy_id, payload.commit_message
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@version_router.get(
    "/strategies/{strategy_id}/versions",
    dependencies=[Depends(security)],
    responses={
        200: {"model": SuccessResponseSchema[list[StrategyVersionResponseSchema]]},
        401: {"model": ErrorResponseSchema},
        404: {"model": ErrorResponseSchema},
    },
)
async def list_strategy_versions(
    strategy_id: str,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    strategy_service: StrategyService = Depends(get_strategy_service),
) -> JSONResponse:
    """List version history of a strategy."""
    status_code, result = await strategy_service.list_versions(
        user.user_id, strategy_id
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@version_router.get(
    "/strategies/{strategy_id}/versions/{version}",
    dependencies=[Depends(security)],
    responses={
        200: {"model": SuccessResponseSchema[StrategyVersionResponseSchema]},
        401: {"model": ErrorResponseSchema},
        404: {"model": ErrorResponseSchema},
    },
)
async def get_strategy_version(
    strategy_id: str,
    version: int,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    strategy_service: StrategyService = Depends(get_strategy_service),
) -> JSONResponse:
    """Fetch details of a specific strategy version."""
    status_code, result = await strategy_service.get_version(
        user.user_id, strategy_id, version
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@version_router.post(
    "/strategies/{strategy_id}/versions/{version}/restore",
    dependencies=[Depends(security)],
    responses={
        200: {"model": SuccessResponseSchema[StrategyResponseSchema]},
        401: {"model": ErrorResponseSchema},
        404: {"model": ErrorResponseSchema},
    },
)
async def restore_strategy_version(
    strategy_id: str,
    version: int,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    strategy_service: StrategyService = Depends(get_strategy_service),
) -> JSONResponse:
    """Restore a historical version snapshot into the current draft."""
    status_code, result = await strategy_service.restore_version(
        user.user_id, strategy_id, version
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@version_router.get(
    "/strategies/{strategy_id}/versions/{version}/diff",
    dependencies=[Depends(security)],
    responses={
        200: {"model": SuccessResponseSchema[VersionDiffResponseSchema]},
        401: {"model": ErrorResponseSchema},
        404: {"model": ErrorResponseSchema},
    },
)
async def diff_strategy_version(
    strategy_id: str,
    version: int,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    strategy_service: StrategyService = Depends(get_strategy_service),
) -> JSONResponse:
    """Compare a version snapshot against the current draft."""
    status_code, result = await strategy_service.diff_version(
        user.user_id, strategy_id, version
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@version_router.put(
    "/strategies/{strategy_id}/versions/{version}/label",
    dependencies=[Depends(security)],
    responses={
        200: {"model": SuccessResponseSchema[StrategyVersionResponseSchema]},
        401: {"model": ErrorResponseSchema},
        404: {"model": ErrorResponseSchema},
    },
)
async def update_strategy_version_label(
    strategy_id: str,
    version: int,
    payload: UpdateVersionLabelRequestSchema,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    strategy_service: StrategyService = Depends(get_strategy_service),
) -> JSONResponse:
    """Update label of a specific strategy version snapshot."""
    status_code, result = await strategy_service.update_version_label(
        user.user_id, strategy_id, version, payload.label
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@version_router.put(
    "/strategies/{strategy_id}/versions/{version}/approval",
    dependencies=[Depends(security)],
    responses={
        200: {"model": SuccessResponseSchema[StrategyVersionResponseSchema]},
        401: {"model": ErrorResponseSchema},
        404: {"model": ErrorResponseSchema},
    },
)
async def update_strategy_version_approval(
    strategy_id: str,
    version: int,
    payload: UpdateVersionApprovalRequestSchema,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    strategy_service: StrategyService = Depends(get_strategy_service),
) -> JSONResponse:
    """Update approval status of a specific strategy version snapshot."""
    status_code, result = await strategy_service.update_version_approval(
        user.user_id, strategy_id, version, payload.approval_status
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@version_router.post(
    "/strategies/{strategy_id}/versions/{version}/golden",
    dependencies=[Depends(security)],
    responses={
        200: {"model": SuccessResponseSchema[StrategyVersionResponseSchema]},
        401: {"model": ErrorResponseSchema},
        404: {"model": ErrorResponseSchema},
    },
)
async def set_strategy_golden_version(
    strategy_id: str,
    version: int,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    strategy_service: StrategyService = Depends(get_strategy_service),
) -> JSONResponse:
    """Set a historical version snapshot as the golden candidate for the strategy."""
    status_code, result = await strategy_service.set_golden_version(
        user.user_id, strategy_id, version
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@version_router.post(
    "/strategies/{strategy_id}/notes",
    dependencies=[Depends(security)],
    responses={
        201: {"model": SuccessResponseSchema[ResearchNoteResponseSchema]},
        401: {"model": ErrorResponseSchema},
        404: {"model": ErrorResponseSchema},
    },
)
async def create_strategy_research_note(
    strategy_id: str,
    payload: ResearchNoteCreateSchema,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    strategy_service: StrategyService = Depends(get_strategy_service),
) -> JSONResponse:
    """Create a new research note for a strategy (optionally linked to a run)."""
    status_code, result = await strategy_service.create_research_note(
        user.user_id, strategy_id, payload.content, payload.run_id
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@version_router.get(
    "/strategies/{strategy_id}/notes",
    dependencies=[Depends(security)],
    responses={
        200: {"model": SuccessResponseSchema[list[ResearchNoteResponseSchema]]},
        401: {"model": ErrorResponseSchema},
        404: {"model": ErrorResponseSchema},
    },
)
async def list_strategy_research_notes(
    strategy_id: str,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    strategy_service: StrategyService = Depends(get_strategy_service),
) -> JSONResponse:
    """List all research notes for a strategy."""
    status_code, result = await strategy_service.list_strategy_notes(
        user.user_id, strategy_id
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@version_router.get(
    "/strategies/{strategy_id}/runs/{run_id}/notes",
    dependencies=[Depends(security)],
    responses={
        200: {"model": SuccessResponseSchema[list[ResearchNoteResponseSchema]]},
        401: {"model": ErrorResponseSchema},
        404: {"model": ErrorResponseSchema},
    },
)
async def list_run_research_notes(
    strategy_id: str,
    run_id: str,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    strategy_service: StrategyService = Depends(get_strategy_service),
) -> JSONResponse:
    """List all research notes for a specific run."""
    status_code, result = await strategy_service.list_run_notes(
        user.user_id, strategy_id, run_id
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)
