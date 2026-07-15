import logging
from typing import Annotated, Optional
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.advices.base_response_handler import BaseResponseHandler
from app.advices.responses import ErrorResponseSchema, SuccessResponseSchema
from app.middlewares.auth_middleware import CurrentUser, get_current_user
from app.modules.strategy_service.schema.strategy_schema import (
    BacktestTriggerRequestSchema,
    ResearchRunTriggerResponseSchema,
    OptimizationRequestSchema,
    WalkForwardRequestSchema,
    MonteCarloRequestSchema,
    PaginatedResearchRunsResponseSchema,
    ResearchRunResponseSchema,
)
from app.modules.strategy_service.routes.strategy_routes import (
    get_strategy_service,
    security,
)
from app.modules.strategy_service.services.strategy_service import StrategyService

logger = logging.getLogger(__name__)
job_router = APIRouter()


@job_router.post(
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
    user: Annotated[CurrentUser, Depends(get_current_user)],
    strategy_service: StrategyService = Depends(get_strategy_service),
) -> JSONResponse:
    """Trigger a backtest task run."""
    status_code, result = await strategy_service.trigger_backtest(
        user_id=user.user_id,
        strategy_id=strategy_id,
        start_date=data.start_date,
        end_date=data.end_date,
        initial_capital=data.initial_capital,
        temporary=data.temporary,
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@job_router.post(
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
    user: Annotated[CurrentUser, Depends(get_current_user)],
    strategy_service: StrategyService = Depends(get_strategy_service),
) -> JSONResponse:
    """Trigger a parameter space optimization run."""
    status_code, result = await strategy_service.trigger_optimization(
        user_id=user.user_id,
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


@job_router.post(
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
    user: Annotated[CurrentUser, Depends(get_current_user)],
    strategy_service: StrategyService = Depends(get_strategy_service),
) -> JSONResponse:
    """Trigger a walkforward validation run."""
    status_code, result = await strategy_service.trigger_walkforward(
        user_id=user.user_id,
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


@job_router.post(
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
    user: Annotated[CurrentUser, Depends(get_current_user)],
    strategy_service: StrategyService = Depends(get_strategy_service),
) -> JSONResponse:
    """Trigger a Monte Carlo robustness run."""
    status_code, result = await strategy_service.trigger_montecarlo(
        user_id=user.user_id,
        strategy_id=strategy_id,
        source_backtest_id=data.source_backtest_id,
        simulation_count=data.simulation_count,
        method=data.method,
        random_seed=data.random_seed,
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@job_router.get(
    "/strategies/{strategy_id}/backtests",
    dependencies=[Depends(security)],
    responses={
        200: {"model": SuccessResponseSchema[PaginatedResearchRunsResponseSchema]},
    },
)
async def list_backtests(
    strategy_id: str,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    status: Optional[str] = None,
    is_favorite: Optional[bool] = None,
    # Default False (not None) so this endpoint keeps excluding Analyse-tab
    # temporary runs with zero frontend changes -- callers that want them
    # pass is_temporary=true explicitly.
    is_temporary: Optional[bool] = False,
    sort_by: str = "updated_at",
    page: int = 1,
    limit: int = 8,
    strategy_service: StrategyService = Depends(get_strategy_service),
) -> JSONResponse:
    """List historical backtests for a strategy."""
    status_code, result = await strategy_service.list_runs(
        user_id=user.user_id,
        strategy_id=strategy_id,
        run_type="BACKTEST",
        status=status,
        is_favorite=is_favorite,
        is_temporary=is_temporary,
        sort_by=sort_by,
        page=page,
        limit=limit,
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@job_router.get(
    "/strategies/{strategy_id}/backtests/{run_id}",
    dependencies=[Depends(security)],
    responses={
        200: {"model": SuccessResponseSchema[ResearchRunResponseSchema]},
    },
)
async def get_backtest(
    strategy_id: str,
    run_id: str,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    strategy_service: StrategyService = Depends(get_strategy_service),
) -> JSONResponse:
    """Fetch details of a single backtest run."""
    status_code, result = await strategy_service.get_run(
        user.user_id, strategy_id=strategy_id, run_id=run_id
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@job_router.get(
    "/strategies/{strategy_id}/optimizations/{run_id}",
    dependencies=[Depends(security)],
    responses={
        200: {"model": SuccessResponseSchema[ResearchRunResponseSchema]},
    },
)
async def get_optimization(
    strategy_id: str,
    run_id: str,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    strategy_service: StrategyService = Depends(get_strategy_service),
) -> JSONResponse:
    """Fetch details of a single optimization run."""
    status_code, result = await strategy_service.get_run(
        user.user_id, strategy_id=strategy_id, run_id=run_id
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@job_router.get(
    "/strategies/{strategy_id}/optimizations",
    dependencies=[Depends(security)],
    responses={
        200: {"model": SuccessResponseSchema[PaginatedResearchRunsResponseSchema]},
    },
)
async def list_optimizations(
    strategy_id: str,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    status: Optional[str] = None,
    is_favorite: Optional[bool] = None,
    sort_by: str = "updated_at",
    page: int = 1,
    limit: int = 8,
    strategy_service: StrategyService = Depends(get_strategy_service),
) -> JSONResponse:
    """List parameter optimizations for a strategy."""
    status_code, result = await strategy_service.list_runs(
        user_id=user.user_id,
        strategy_id=strategy_id,
        run_type="OPTIMIZATION",
        status=status,
        is_favorite=is_favorite,
        sort_by=sort_by,
        page=page,
        limit=limit,
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@job_router.get(
    "/strategies/{strategy_id}/walkforwards/{run_id}",
    dependencies=[Depends(security)],
    responses={
        200: {"model": SuccessResponseSchema[ResearchRunResponseSchema]},
    },
)
async def get_walkforward(
    strategy_id: str,
    run_id: str,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    strategy_service: StrategyService = Depends(get_strategy_service),
) -> JSONResponse:
    """Fetch details of a single walkforward run."""
    status_code, result = await strategy_service.get_run(
        user.user_id, strategy_id=strategy_id, run_id=run_id
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@job_router.get(
    "/strategies/{strategy_id}/walkforwards",
    dependencies=[Depends(security)],
    responses={
        200: {"model": SuccessResponseSchema[PaginatedResearchRunsResponseSchema]},
    },
)
async def list_walkforwards(
    strategy_id: str,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    status: Optional[str] = None,
    is_favorite: Optional[bool] = None,
    sort_by: str = "updated_at",
    page: int = 1,
    limit: int = 8,
    strategy_service: StrategyService = Depends(get_strategy_service),
) -> JSONResponse:
    """List walkforward runs for a strategy."""
    status_code, result = await strategy_service.list_runs(
        user_id=user.user_id,
        strategy_id=strategy_id,
        run_type="WALKFORWARD",
        status=status,
        is_favorite=is_favorite,
        sort_by=sort_by,
        page=page,
        limit=limit,
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@job_router.get(
    "/strategies/{strategy_id}/montecarlos/{run_id}",
    dependencies=[Depends(security)],
    responses={
        200: {"model": SuccessResponseSchema[ResearchRunResponseSchema]},
    },
)
async def get_montecarlo(
    strategy_id: str,
    run_id: str,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    strategy_service: StrategyService = Depends(get_strategy_service),
) -> JSONResponse:
    """Fetch details of a single Monte Carlo run."""
    status_code, result = await strategy_service.get_run(
        user.user_id, strategy_id=strategy_id, run_id=run_id
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@job_router.get(
    "/strategies/{strategy_id}/montecarlos",
    dependencies=[Depends(security)],
    responses={
        200: {"model": SuccessResponseSchema[PaginatedResearchRunsResponseSchema]},
    },
)
async def list_montecarlos(
    strategy_id: str,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    status: Optional[str] = None,
    is_favorite: Optional[bool] = None,
    sort_by: str = "updated_at",
    page: int = 1,
    limit: int = 8,
    strategy_service: StrategyService = Depends(get_strategy_service),
) -> JSONResponse:
    """List Monte Carlo simulation runs for a strategy."""
    status_code, result = await strategy_service.list_runs(
        user_id=user.user_id,
        strategy_id=strategy_id,
        run_type="MONTECARLO",
        status=status,
        is_favorite=is_favorite,
        sort_by=sort_by,
        page=page,
        limit=limit,
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)
