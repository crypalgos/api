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
    session: AsyncSession = Depends(get_db)
) -> StrategyService:
    return StrategyService(
        StrategyRepository(session),
        ResearchRunRepository(session)
    )

# ─────────────────────────────────────────────────────────────────────────────
# Strategies APIs
# ─────────────────────────────────────────────────────────────────────────────

@strategy_router.post(
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
    strategy_service: StrategyService = Depends(get_strategy_service)
) -> JSONResponse:
    """Create a new visual React Flow strategy canvas, auto-generating standard code base."""
    status_code, result = await strategy_service.create_strategy(
        user_id=user["user_id"],
        name=strategy_data.name,
        description=strategy_data.description,
        canvas_json=strategy_data.canvas_json
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@strategy_router.get(
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
    strategy_service: StrategyService = Depends(get_strategy_service)
) -> JSONResponse:
    """List saved strategies belonging to the authenticated user with pagination, filtering, and search."""
    status_code, result = await strategy_service.list_strategies(
        user_id=user["user_id"],
        page=page,
        limit=limit,
        search=search,
        is_template=is_template,
        archived=archived
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@strategy_router.get(
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
    strategy_service: StrategyService = Depends(get_strategy_service)
) -> JSONResponse:
    """Fetch a specific visual strategy canvas."""
    status_code, result = await strategy_service.get_strategy(user["user_id"], strategy_id)
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@strategy_router.put(
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
    strategy_service: StrategyService = Depends(get_strategy_service)
) -> JSONResponse:
    """Save the visual canvas node/edge graph and recompile it to Python strategy code."""
    status_code, result = await strategy_service.update_canvas(
        user_id=user["user_id"],
        strategy_id=strategy_id,
        canvas_json=canvas_data.canvas_json,
        name=canvas_data.name,
        description=canvas_data.description
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@strategy_router.put(
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
    strategy_service: StrategyService = Depends(get_strategy_service)
) -> JSONResponse:
    """Overwrite standard compiled code with custom user edits inside Monaco editor."""
    status_code, result = await strategy_service.save_custom_code(
        user_id=user["user_id"],
        strategy_id=strategy_id,
        code=code_data.code
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@strategy_router.post(
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
    strategy_service: StrategyService = Depends(get_strategy_service)
) -> JSONResponse:
    """Reset custom Monaco code changes and re-compile from visual canvas DAG layout."""
    status_code, result = await strategy_service.reset_to_visual_builder(user["user_id"], strategy_id)
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@strategy_router.delete(
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
    strategy_service: StrategyService = Depends(get_strategy_service)
) -> JSONResponse:
    """Archive a visual strategy canvas owned by the authenticated user."""
    status_code, result = await strategy_service.delete_strategy(user["user_id"], strategy_id)
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@strategy_router.post(
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
    strategy_service: StrategyService = Depends(get_strategy_service)
) -> JSONResponse:
    """Restore/unarchive a strategy from soft delete."""
    status_code, result = await strategy_service.restore_strategy(user["user_id"], strategy_id)
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


# ─────────────────────────────────────────────────────────────────────────────
# Strategy Versioning APIs
# ─────────────────────────────────────────────────────────────────────────────

@strategy_router.post(
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
    user: Annotated[dict, Depends(get_current_user)],
    strategy_service: StrategyService = Depends(get_strategy_service)
) -> JSONResponse:
    """Manually save a snapshot version of the strategy draft."""
    status_code, result = await strategy_service.save_version(
        user["user_id"], strategy_id, payload.commit_message
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@strategy_router.get(
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
    user: Annotated[dict, Depends(get_current_user)],
    strategy_service: StrategyService = Depends(get_strategy_service)
) -> JSONResponse:
    """List version history of a strategy."""
    status_code, result = await strategy_service.list_versions(user["user_id"], strategy_id)
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@strategy_router.get(
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
    user: Annotated[dict, Depends(get_current_user)],
    strategy_service: StrategyService = Depends(get_strategy_service)
) -> JSONResponse:
    """Fetch details of a specific strategy version."""
    status_code, result = await strategy_service.get_version(user["user_id"], strategy_id, version)
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@strategy_router.post(
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
    user: Annotated[dict, Depends(get_current_user)],
    strategy_service: StrategyService = Depends(get_strategy_service)
) -> JSONResponse:
    """Restore a historical version snapshot into the current draft."""
    status_code, result = await strategy_service.restore_version(user["user_id"], strategy_id, version)
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@strategy_router.get(
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
    user: Annotated[dict, Depends(get_current_user)],
    strategy_service: StrategyService = Depends(get_strategy_service)
) -> JSONResponse:
    """Compare a version snapshot against the current draft."""
    status_code, result = await strategy_service.diff_version(user["user_id"], strategy_id, version)
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@strategy_router.put(
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
    user: Annotated[dict, Depends(get_current_user)],
    strategy_service: StrategyService = Depends(get_strategy_service)
) -> JSONResponse:
    """Update label of a specific strategy version snapshot."""
    status_code, result = await strategy_service.update_version_label(
        user["user_id"], strategy_id, version, payload.label
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@strategy_router.put(
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
    user: Annotated[dict, Depends(get_current_user)],
    strategy_service: StrategyService = Depends(get_strategy_service)
) -> JSONResponse:
    """Update approval status of a specific strategy version snapshot."""
    status_code, result = await strategy_service.update_version_approval(
        user["user_id"], strategy_id, version, payload.approval_status
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@strategy_router.post(
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
    user: Annotated[dict, Depends(get_current_user)],
    strategy_service: StrategyService = Depends(get_strategy_service)
) -> JSONResponse:
    """Set a historical version snapshot as the golden candidate for the strategy."""
    status_code, result = await strategy_service.set_golden_version(
        user["user_id"], strategy_id, version
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@strategy_router.post(
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
    user: Annotated[dict, Depends(get_current_user)],
    strategy_service: StrategyService = Depends(get_strategy_service)
) -> JSONResponse:
    """Create a new research note for a strategy (optionally linked to a run)."""
    status_code, result = await strategy_service.create_research_note(
        user["user_id"], strategy_id, payload.content, payload.run_id
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@strategy_router.get(
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
    user: Annotated[dict, Depends(get_current_user)],
    strategy_service: StrategyService = Depends(get_strategy_service)
) -> JSONResponse:
    """List all research notes for a strategy."""
    status_code, result = await strategy_service.list_strategy_notes(user["user_id"], strategy_id)
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@strategy_router.get(
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
    user: Annotated[dict, Depends(get_current_user)],
    strategy_service: StrategyService = Depends(get_strategy_service)
) -> JSONResponse:
    """List all research notes for a specific run."""
    status_code, result = await strategy_service.list_run_notes(user["user_id"], strategy_id, run_id)
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


# ─────────────────────────────────────────────────────────────────────────────
# Research Runs APIs
# ─────────────────────────────────────────────────────────────────────────────



@strategy_router.post(
    "/strategies/{strategy_id}/backtests",
    dependencies=[Depends(security)],
    responses={
        202: {"model": SuccessResponseSchema[ResearchRunTriggerResponseSchema]},
        401: {"model": ErrorResponseSchema},
    },
)
async def trigger_backtest(
    strategy_id: str,
    data: BacktestTriggerRequestSchema,
    user: Annotated[dict, Depends(get_current_user)],
    strategy_service: StrategyService = Depends(get_strategy_service)
) -> JSONResponse:
    """Trigger a backtest task run."""
    status_code, result = await strategy_service.trigger_backtest(
        user_id=user["user_id"],
        strategy_id=strategy_id,
        start_date=data.start_date,
        end_date=data.end_date,
        initial_capital=data.initial_capital
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@strategy_router.post(
    "/strategies/{strategy_id}/optimizations",
    dependencies=[Depends(security)],
    responses={
        202: {"model": SuccessResponseSchema[ResearchRunTriggerResponseSchema]},
        401: {"model": ErrorResponseSchema},
    },
)
async def trigger_optimization(
    strategy_id: str,
    data: OptimizationRequestSchema,
    user: Annotated[dict, Depends(get_current_user)],
    strategy_service: StrategyService = Depends(get_strategy_service)
) -> JSONResponse:
    """Trigger a parameter space optimization run."""
    status_code, result = await strategy_service.trigger_optimization(
        user_id=user["user_id"],
        strategy_id=strategy_id,
        start_date=data.start_date,
        end_date=data.end_date,
        initial_capital=data.initial_capital,
        parameter_space=[p.model_dump() for p in data.parameter_space],
        constraints=[c.model_dump() for c in (data.constraints or [])],
        objective=data.objective,
        search_type=data.search_type,
        max_runs=data.max_runs,
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@strategy_router.post(
    "/strategies/{strategy_id}/walkforwards",
    dependencies=[Depends(security)],
    responses={
        202: {"model": SuccessResponseSchema[ResearchRunTriggerResponseSchema]},
        401: {"model": ErrorResponseSchema},
    },
)
async def trigger_walkforward(
    strategy_id: str,
    data: WalkForwardRequestSchema,
    user: Annotated[dict, Depends(get_current_user)],
    strategy_service: StrategyService = Depends(get_strategy_service)
) -> JSONResponse:
    """Trigger a walkforward validation run."""
    status_code, result = await strategy_service.trigger_walkforward(
        user_id=user["user_id"],
        strategy_id=strategy_id,
        start_date=data.start_date,
        end_date=data.end_date,
        initial_capital=data.initial_capital,
        train_period_months=data.train_period_months,
        test_period_months=data.test_period_months,
        step_months=data.step_months,
        objective=data.objective,
        parameter_space=[p.model_dump() for p in data.parameter_space],
        constraints=[c.model_dump() for c in (data.constraints or [])],
        window_type=data.window_type,
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@strategy_router.post(
    "/strategies/{strategy_id}/montecarlos",
    dependencies=[Depends(security)],
    responses={
        202: {"model": SuccessResponseSchema[ResearchRunTriggerResponseSchema]},
        401: {"model": ErrorResponseSchema},
    },
)
async def trigger_montecarlo(
    strategy_id: str,
    data: MonteCarloRequestSchema,
    user: Annotated[dict, Depends(get_current_user)],
    strategy_service: StrategyService = Depends(get_strategy_service)
) -> JSONResponse:
    """Trigger a Monte Carlo robustness run."""
    status_code, result = await strategy_service.trigger_montecarlo(
        user_id=user["user_id"],
        strategy_id=strategy_id,
        source_backtest_id=data.source_backtest_id,
        simulation_count=data.simulation_count,
        method=data.method,
        random_seed=data.random_seed
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


# ─────────────────────────────────────────────────────────────────────────────
# Listing & specific run getters
# ─────────────────────────────────────────────────────────────────────────────

@strategy_router.get(
    "/strategies/{strategy_id}/backtests",
    dependencies=[Depends(security)],
    responses={
        200: {"model": SuccessResponseSchema[PaginatedResearchRunsResponseSchema]},
    },
)
async def list_backtests(
    strategy_id: str,
    user: Annotated[dict, Depends(get_current_user)],
    status: Optional[str] = None,
    is_favorite: Optional[bool] = None,
    sort_by: str = "updated_at",
    page: int = 1,
    limit: int = 8,
    strategy_service: StrategyService = Depends(get_strategy_service)
) -> JSONResponse:
    """List historical backtests for a strategy."""
    status_code, result = await strategy_service.list_runs(
        user_id=user["user_id"], strategy_id=strategy_id, run_type="BACKTEST",
        status=status, is_favorite=is_favorite, sort_by=sort_by, page=page, limit=limit
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@strategy_router.get(
    "/strategies/{strategy_id}/optimizations",
    dependencies=[Depends(security)],
    responses={
        200: {"model": SuccessResponseSchema[PaginatedResearchRunsResponseSchema]},
    },
)
async def list_optimizations(
    strategy_id: str,
    user: Annotated[dict, Depends(get_current_user)],
    status: Optional[str] = None,
    is_favorite: Optional[bool] = None,
    sort_by: str = "updated_at",
    page: int = 1,
    limit: int = 8,
    strategy_service: StrategyService = Depends(get_strategy_service)
) -> JSONResponse:
    """List parameter optimizations for a strategy."""
    status_code, result = await strategy_service.list_runs(
        user_id=user["user_id"], strategy_id=strategy_id, run_type="OPTIMIZATION",
        status=status, is_favorite=is_favorite, sort_by=sort_by, page=page, limit=limit
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@strategy_router.get(
    "/strategies/{strategy_id}/walkforwards",
    dependencies=[Depends(security)],
    responses={
        200: {"model": SuccessResponseSchema[PaginatedResearchRunsResponseSchema]},
    },
)
async def list_walkforwards(
    strategy_id: str,
    user: Annotated[dict, Depends(get_current_user)],
    status: Optional[str] = None,
    is_favorite: Optional[bool] = None,
    sort_by: str = "updated_at",
    page: int = 1,
    limit: int = 8,
    strategy_service: StrategyService = Depends(get_strategy_service)
) -> JSONResponse:
    """List walkforward runs for a strategy."""
    status_code, result = await strategy_service.list_runs(
        user_id=user["user_id"], strategy_id=strategy_id, run_type="WALKFORWARD",
        status=status, is_favorite=is_favorite, sort_by=sort_by, page=page, limit=limit
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@strategy_router.get(
    "/strategies/{strategy_id}/montecarlos",
    dependencies=[Depends(security)],
    responses={
        200: {"model": SuccessResponseSchema[PaginatedResearchRunsResponseSchema]},
    },
)
async def list_montecarlos(
    strategy_id: str,
    user: Annotated[dict, Depends(get_current_user)],
    status: Optional[str] = None,
    is_favorite: Optional[bool] = None,
    sort_by: str = "updated_at",
    page: int = 1,
    limit: int = 8,
    strategy_service: StrategyService = Depends(get_strategy_service)
) -> JSONResponse:
    """List Monte Carlo runs for a strategy."""
    status_code, result = await strategy_service.list_runs(
        user_id=user["user_id"], strategy_id=strategy_id, run_type="MONTECARLO",
        status=status, is_favorite=is_favorite, sort_by=sort_by, page=page, limit=limit
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@strategy_router.get(
    "/strategies/{strategy_id}/backtests/{backtest_id}",
    dependencies=[Depends(security)],
)
async def get_backtest(
    strategy_id: str,
    backtest_id: str,
    user: Annotated[dict, Depends(get_current_user)],
    strategy_service: StrategyService = Depends(get_strategy_service)
) -> JSONResponse:
    """Get detailed backtest run (metadata + report payload from storage)."""
    status_code, result = await strategy_service.get_run(user["user_id"], strategy_id, backtest_id)
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@strategy_router.get(
    "/strategies/{strategy_id}/optimizations/{optimization_id}",
    dependencies=[Depends(security)],
)
async def get_optimization(
    strategy_id: str,
    optimization_id: str,
    user: Annotated[dict, Depends(get_current_user)],
    strategy_service: StrategyService = Depends(get_strategy_service)
) -> JSONResponse:
    """Get detailed optimization run (metadata + report payload)."""
    status_code, result = await strategy_service.get_run(user["user_id"], strategy_id, optimization_id)
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@strategy_router.get(
    "/strategies/{strategy_id}/walkforwards/{walkforward_id}",
    dependencies=[Depends(security)],
)
async def get_walkforward(
    strategy_id: str,
    walkforward_id: str,
    user: Annotated[dict, Depends(get_current_user)],
    strategy_service: StrategyService = Depends(get_strategy_service)
) -> JSONResponse:
    """Get detailed walkforward run (metadata + report payload)."""
    status_code, result = await strategy_service.get_run(user["user_id"], strategy_id, walkforward_id)
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@strategy_router.get(
    "/strategies/{strategy_id}/montecarlos/{montecarlo_id}",
    dependencies=[Depends(security)],
)
async def get_montecarlo(
    strategy_id: str,
    montecarlo_id: str,
    user: Annotated[dict, Depends(get_current_user)],
    strategy_service: StrategyService = Depends(get_strategy_service)
) -> JSONResponse:
    """Get detailed Monte Carlo run (metadata + report payload)."""
    status_code, result = await strategy_service.get_run(user["user_id"], strategy_id, montecarlo_id)
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


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
    strategy_service: StrategyService = Depends(get_strategy_service)
) -> JSONResponse:
    """Edit a run's name and/or description."""
    status_code, result = await strategy_service.edit_run(
        user_id=user["user_id"], run_id=run_id, name=data.name, description=data.description
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
    strategy_service: StrategyService = Depends(get_strategy_service)
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
    strategy_service: StrategyService = Depends(get_strategy_service)
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
    strategy_service: StrategyService = Depends(get_strategy_service)
) -> JSONResponse:
    """Fetch real-time active task progress metrics."""
    status_code, result = await strategy_service.get_run_progress(user["user_id"], run_id)
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@strategy_router.get(
    "/strategies/{strategy_id}/latest/{run_type}",
    dependencies=[Depends(security)],
)
async def get_latest_run(
    strategy_id: str,
    run_type: str,
    user: Annotated[dict, Depends(get_current_user)],
    strategy_service: StrategyService = Depends(get_strategy_service)
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
    strategy_service: StrategyService = Depends(get_strategy_service)
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
    strategy_service: StrategyService = Depends(get_strategy_service)
) -> JSONResponse:
    """Download the heavy dataset payload from storage and extract specific chart curves."""
    status_code, result = await strategy_service.get_run_dataset_chart(
        user["user_id"], run_id=run_id, dataset_name=dataset_name
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)
