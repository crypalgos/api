import logging
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.advices.base_response_handler import BaseResponseHandler
from app.advices.responses import ErrorResponseSchema, SuccessResponseSchema
from app.db.connect_db import get_db
from app.middlewares.auth_middleware import get_current_user
from app.modules.strategy_service.repositories.backtest_repository import BacktestRepository
from app.modules.strategy_service.repositories.optimization_repository import OptimizationRepository
from app.modules.strategy_service.repositories.walkforward_repository import WalkForwardRepository
from app.modules.strategy_service.repositories.montecarlo_repository import MonteCarloRepository

# Service & Repository imports
from app.modules.strategy_service.repositories.strategy_repository import StrategyRepository
from app.modules.strategy_service.schema.strategy_schema import (
    BacktestResponseSchema,
    BacktestTriggerRequestSchema,
    SaveCodeRequestSchema,
    UpdateCanvasRequestSchema,
    StrategyCreateSchema,
    StrategyResponseSchema,
    BacktestTriggerResponseSchema,
    PaginatedStrategiesResponseSchema,
    PaginatedBacktestsResponseSchema,
    OptimizationRequestSchema,
    OptimizationTriggerResponseSchema,
    OptimizationRunResponseSchema,
    PaginatedOptimizationRunsResponseSchema,
    WalkForwardRequestSchema,
    WalkForwardTriggerResponseSchema,
    WalkForwardRunResponseSchema,
    PaginatedWalkForwardRunsResponseSchema,
    MonteCarloRequestSchema,
    MonteCarloTriggerResponseSchema,
    MonteCarloRunResponseSchema,
    PaginatedMonteCarloRunsResponseSchema,
)
from app.modules.strategy_service.services.strategy_service import StrategyService
from app.modules.strategy_service.services.backtest_service import BacktestService
from app.modules.strategy_service.services.optimization_service import OptimizationService
from app.modules.strategy_service.services.walkforward_service import WalkForwardService
from app.modules.strategy_service.services.montecarlo_service import MonteCarloService

logger = logging.getLogger(__name__)

security = HTTPBearer()
strategy_router = APIRouter(prefix="/strategies", tags=["Strategies"])

async def get_strategy_service(session: AsyncSession = Depends(get_db)) -> StrategyService:
    return StrategyService(StrategyRepository(session))

async def get_backtest_service(session: AsyncSession = Depends(get_db)) -> BacktestService:
    return BacktestService(StrategyRepository(session), BacktestRepository(session))

async def get_optimization_service(session: AsyncSession = Depends(get_db)) -> OptimizationService:
    return OptimizationService(StrategyRepository(session), OptimizationRepository(session))

async def get_walkforward_service(session: AsyncSession = Depends(get_db)) -> WalkForwardService:
    return WalkForwardService(StrategyRepository(session), WalkForwardRepository(session))

async def get_montecarlo_service(session: AsyncSession = Depends(get_db)) -> MonteCarloService:
    return MonteCarloService(StrategyRepository(session), BacktestRepository(session), MonteCarloRepository(session))

@strategy_router.post(
    "",
    dependencies=[Depends(security)],
    responses={
        201: {
            "model": SuccessResponseSchema[StrategyResponseSchema],
            "description": "Visual strategy canvas successfully created",
        },
        401: {
            "model": ErrorResponseSchema,
            "description": "Invalid or missing authentication token",
        },
        422: {
            "model": ErrorResponseSchema,
            "description": "Validation error for the canvas payload",
        },
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
    "",
    dependencies=[Depends(security)],
    responses={
        200: {
            "model": SuccessResponseSchema[PaginatedStrategiesResponseSchema],
            "description": "Successfully listed paginated strategies belonging to the user",
        },
        401: {
            "model": ErrorResponseSchema,
            "description": "Invalid or missing authentication token",
        },
    },
)
async def list_strategies(
    user: Annotated[dict, Depends(get_current_user)],
    page: int = 1,
    limit: int = 8,
    search: str = "",
    strategy_service: StrategyService = Depends(get_strategy_service)
) -> JSONResponse:
    """List saved strategies belonging to the authenticated user with pagination and search."""
    status_code, result = await strategy_service.list_strategies(
        user_id=user["user_id"],
        page=page,
        limit=limit,
        search=search
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)

@strategy_router.get(
    "/{strategy_id}",
    dependencies=[Depends(security)],
    responses={
        200: {
            "model": SuccessResponseSchema[StrategyResponseSchema],
            "description": "Successfully retrieved target strategy",
        },
        401: {
            "model": ErrorResponseSchema,
            "description": "Invalid or missing authentication token",
        },
        404: {
            "model": ErrorResponseSchema,
            "description": "Strategy not found",
        },
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
    "/{strategy_id}/code",
    dependencies=[Depends(security)],
    responses={
        200: {
            "model": SuccessResponseSchema[dict],
            "description": "Successfully saved Monaco code modification, visual flow desynchronized",
        },
        401: {
            "model": ErrorResponseSchema,
            "description": "Invalid or missing authentication token",
        },
        404: {
            "model": ErrorResponseSchema,
            "description": "Strategy not found",
        },
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

@strategy_router.put(
    "/{strategy_id}/canvas",
    dependencies=[Depends(security)],
    responses={
        200: {
            "model": SuccessResponseSchema[StrategyResponseSchema],
            "description": "Canvas saved and recompiled to Python successfully",
        },
        401: {
            "model": ErrorResponseSchema,
            "description": "Invalid or missing authentication token",
        },
        404: {
            "model": ErrorResponseSchema,
            "description": "Strategy not found",
        },
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
        description=canvas_data.description,
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)

@strategy_router.post(
    "/{strategy_id}/reset-builder",
    dependencies=[Depends(security)],
    responses={
        200: {
            "model": SuccessResponseSchema[StrategyResponseSchema],
            "description": "Successfully reset code custom changes back to visual canvas sync status",
        },
        401: {
            "model": ErrorResponseSchema,
            "description": "Invalid or missing authentication token",
        },
        404: {
            "model": ErrorResponseSchema,
            "description": "Strategy not found",
        },
    },
)
async def reset_to_visual_builder(
    strategy_id: str,
    user: Annotated[dict, Depends(get_current_user)],
    strategy_service: StrategyService = Depends(get_strategy_service)
) -> JSONResponse:
    """Reset strategy state, overwriting custom code edits with re-compiled Visual Canvas code."""
    status_code, result = await strategy_service.reset_to_visual_builder(
        user_id=user["user_id"],
        strategy_id=strategy_id
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)

@strategy_router.post(
    "/{strategy_id}/backtest",
    dependencies=[Depends(security)],
    responses={
        202: {
            "model": SuccessResponseSchema[BacktestTriggerResponseSchema],
            "description": "Backtest enqueued successfully",
        },
        401: {
            "model": ErrorResponseSchema,
            "description": "Invalid or missing authentication token",
        },
        404: {
            "model": ErrorResponseSchema,
            "description": "Strategy not found",
        },
    },
)
async def execute_backtest(
    strategy_id: str,
    bt_data: BacktestTriggerRequestSchema,
    user: Annotated[dict, Depends(get_current_user)],
    backtest_service: BacktestService = Depends(get_backtest_service)
) -> JSONResponse:
    """Run an institutional-grade simulation backtest asynchronously in a background sandbox."""
    status_code, result = await backtest_service.trigger_backtest(
        user_id=user["user_id"],
        strategy_id=strategy_id,
        start_date=bt_data.start_date,
        end_date=bt_data.end_date,
        initial_capital=bt_data.initial_capital,
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)

@strategy_router.delete(
    "/{strategy_id}",
    dependencies=[Depends(security)],
    responses={
        200: {
            "model": SuccessResponseSchema[dict],
            "description": "Strategy permanently deleted",
        },
        401: {
            "model": ErrorResponseSchema,
            "description": "Invalid or missing authentication token",
        },
        404: {
            "model": ErrorResponseSchema,
            "description": "Strategy not found",
        },
    },
)
async def delete_strategy(
    strategy_id: str,
    user: Annotated[dict, Depends(get_current_user)],
    strategy_service: StrategyService = Depends(get_strategy_service)
) -> JSONResponse:
    """Permanently delete a strategy owned by the authenticated user."""
    status_code, result = await strategy_service.delete_strategy(
        user_id=user["user_id"],
        strategy_id=strategy_id
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)

@strategy_router.get(
    "/{strategy_id}/backtests",
    dependencies=[Depends(security)],
    responses={
        200: {
            "model": SuccessResponseSchema[PaginatedBacktestsResponseSchema],
            "description": "List all paginated backtest runs for a given strategy",
        },
        401: {
            "model": ErrorResponseSchema,
            "description": "Invalid or missing authentication token",
        },
        404: {
            "model": ErrorResponseSchema,
            "description": "Strategy not found",
        },
    },
)
async def list_strategy_backtests(
    strategy_id: str,
    user: Annotated[dict, Depends(get_current_user)],
    page: int = 1,
    limit: int = 8,
    backtest_service: BacktestService = Depends(get_backtest_service)
) -> JSONResponse:
    """List historical backtest results for a specific strategy with pagination and filtering."""
    status_code, result = await backtest_service.list_backtests(
        user_id=user["user_id"],
        strategy_id=strategy_id,
        page=page,
        limit=limit
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)

@strategy_router.get(
    "/{strategy_id}/backtests/{backtest_id}",
    dependencies=[Depends(security)],
    responses={
        200: {
            "model": SuccessResponseSchema[BacktestResponseSchema],
            "description": "Successfully retrieved target backtest run with curves intact",
        },
        401: {
            "model": ErrorResponseSchema,
            "description": "Invalid or missing authentication token",
        },
        404: {
            "model": ErrorResponseSchema,
            "description": "Strategy or backtest run not found",
        },
    },
)
async def get_backtest(
    strategy_id: str,
    backtest_id: str,
    user: Annotated[dict, Depends(get_current_user)],
    backtest_service: BacktestService = Depends(get_backtest_service)
) -> JSONResponse:
    """Fetch a specific backtest run with full detailed curves and performance logs."""
    status_code, result = await backtest_service.get_backtest(
        user_id=user["user_id"],
        strategy_id=strategy_id,
        backtest_id=backtest_id
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)

@strategy_router.delete(
    "/{strategy_id}/backtests/{backtest_id}",
    dependencies=[Depends(security)],
    responses={
        200: {
            "model": SuccessResponseSchema[dict],
            "description": "Backtest run deleted successfully",
        },
        401: {
            "model": ErrorResponseSchema,
            "description": "Invalid or missing authentication token",
        },
        404: {
            "model": ErrorResponseSchema,
            "description": "Strategy or backtest run not found",
        },
    },
)
async def delete_backtest(
    strategy_id: str,
    backtest_id: str,
    user: Annotated[dict, Depends(get_current_user)],
    backtest_service: BacktestService = Depends(get_backtest_service)
) -> JSONResponse:
    """Permanently delete a specific backtest run."""
    status_code, result = await backtest_service.delete_backtest(
        user_id=user["user_id"],
        strategy_id=strategy_id,
        backtest_id=backtest_id
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


# ─────────────────────────────────────────────────────────────────────────────
# Optimization Routes
# ─────────────────────────────────────────────────────────────────────────────

@strategy_router.post(
    "/{strategy_id}/optimize",
    dependencies=[Depends(security)],
    responses={
        202: {
            "model": SuccessResponseSchema[OptimizationTriggerResponseSchema],
            "description": "Optimization job enqueued"
        },
        401: {
            "model": ErrorResponseSchema,
            "description": "Invalid or missing authentication token",
        },
        404: {
            "model": ErrorResponseSchema, 
            "description": "Strategy not found"
        },
    },
)
async def trigger_optimization(
    strategy_id: str,
    opt_data: OptimizationRequestSchema,
    user: Annotated[dict, Depends(get_current_user)],
    optimization_service: OptimizationService = Depends(get_optimization_service)
) -> JSONResponse:
    """Submit a parameter optimization job — grid or random search over the strategy's parameter space."""
    status_code, result = await optimization_service.trigger_optimization(
        user_id=user["user_id"],
        strategy_id=strategy_id,
        start_date=opt_data.start_date,
        end_date=opt_data.end_date,
        parameter_space=opt_data.parameter_space,
        objective=opt_data.objective,
        search_type=opt_data.search_type,
        max_runs=opt_data.max_runs,
        constraints=opt_data.constraints,
        initial_capital=opt_data.initial_capital,
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@strategy_router.get(
    "/{strategy_id}/optimizations",
    dependencies=[Depends(security)],
    responses={
        200: {
            "model": SuccessResponseSchema[PaginatedOptimizationRunsResponseSchema],
            "description": "Paginated list of optimization runs"
        },
        401: {
            "model": ErrorResponseSchema,
            "description": "Invalid or missing authentication token",
        },
    },
)
async def list_optimization_runs(
    strategy_id: str,
    user: Annotated[dict, Depends(get_current_user)],
    page: int = 1,
    limit: int = 8,
    search: str = "",
    optimization_service: OptimizationService = Depends(get_optimization_service)
) -> JSONResponse:
    """List all optimization runs for a strategy with pagination."""
    status_code, result = await optimization_service.list_optimization_runs(
        user_id=user["user_id"], strategy_id=strategy_id, page=page, limit=limit, search=search
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@strategy_router.get(
    "/{strategy_id}/optimizations/{run_id}",
    dependencies=[Depends(security)],
    responses={
        200: {
            "model": SuccessResponseSchema[OptimizationRunResponseSchema],
            "description": "Optimization run details with leaderboard"
        },
        401: {
            "model": ErrorResponseSchema,
            "description": "Invalid or missing authentication token",
        },
        404: {
            "model": ErrorResponseSchema, 
            "description": "Run not found"
        },
    },
)
async def get_optimization_run(
    strategy_id: str,
    run_id: str,
    user: Annotated[dict, Depends(get_current_user)],
    optimization_service: OptimizationService = Depends(get_optimization_service)
) -> JSONResponse:
    """Fetch a specific optimization run with best result and top-50 leaderboard."""
    status_code, result = await optimization_service.get_optimization_run(
        user_id=user["user_id"], strategy_id=strategy_id, run_id=run_id
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


# ─────────────────────────────────────────────────────────────────────────────
# Walk Forward Routes
# ─────────────────────────────────────────────────────────────────────────────

@strategy_router.post(
    "/{strategy_id}/walkforward",
    dependencies=[Depends(security)],
    responses={
        202: {
            "model": SuccessResponseSchema[WalkForwardTriggerResponseSchema],
            "description": "Walk-forward job enqueued"
        },
        401: {
            "model": ErrorResponseSchema,
            "description": "Invalid or missing authentication token",
        },
        404: {
            "model": ErrorResponseSchema, 
            "description": "Strategy not found"
        },
    },
)
async def trigger_walkforward(
    strategy_id: str,
    wf_data: WalkForwardRequestSchema,
    user: Annotated[dict, Depends(get_current_user)],
    walkforward_service: WalkForwardService = Depends(get_walkforward_service)
) -> JSONResponse:
    """Submit a walk-forward out-of-sample validation job."""
    status_code, result = await walkforward_service.trigger_walkforward(
        user_id=user["user_id"],
        strategy_id=strategy_id,
        start_date=wf_data.start_date,
        end_date=wf_data.end_date,
        parameter_space=wf_data.parameter_space,
        objective=wf_data.objective,
        train_period_months=wf_data.train_period_months,
        test_period_months=wf_data.test_period_months,
        step_months=wf_data.step_months,
        constraints=wf_data.constraints,
        initial_capital=wf_data.initial_capital,
        window_type=wf_data.window_type,
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@strategy_router.get(
    "/{strategy_id}/walkforwards",
    dependencies=[Depends(security)],
    responses={
        200: {
            "model": SuccessResponseSchema[PaginatedWalkForwardRunsResponseSchema],
            "description": "Paginated list of walk-forward runs"
        },
        401: {
            "model": ErrorResponseSchema,
            "description": "Invalid or missing authentication token",
        },
    },
)
async def list_walkforward_runs(
    strategy_id: str,
    user: Annotated[dict, Depends(get_current_user)],
    page: int = 1,
    limit: int = 8,
    search: str = "",
    walkforward_service: WalkForwardService = Depends(get_walkforward_service)
) -> JSONResponse:
    """List all walk-forward runs for a strategy with pagination."""
    status_code, result = await walkforward_service.list_walkforward_runs(
        user_id=user["user_id"], strategy_id=strategy_id, page=page, limit=limit, search=search
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@strategy_router.get(
    "/{strategy_id}/walkforwards/{run_id}",
    dependencies=[Depends(security)],
    responses={
        200: {
            "model": SuccessResponseSchema[WalkForwardRunResponseSchema],
            "description": "Walk-forward run details with window summary"
        },
        401: {
            "model": ErrorResponseSchema,
            "description": "Invalid or missing authentication token",
        },
        404: {
            "model": ErrorResponseSchema, 
            "description": "Run not found"
        },
    },
)
async def get_walkforward_run(
    strategy_id: str,
    run_id: str,
    user: Annotated[dict, Depends(get_current_user)],
    walkforward_service: WalkForwardService = Depends(get_walkforward_service)
) -> JSONResponse:
    """Fetch a specific walk-forward run with full KPI summary and window table."""
    status_code, result = await walkforward_service.get_walkforward_run(
        user_id=user["user_id"], strategy_id=strategy_id, run_id=run_id
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


# ─────────────────────────────────────────────────────────────────────────────
# Monte Carlo Routes
# ─────────────────────────────────────────────────────────────────────────────

@strategy_router.post(
    "/{strategy_id}/montecarlo",
    dependencies=[Depends(security)],
    responses={
        202: {
            "model": SuccessResponseSchema[MonteCarloTriggerResponseSchema],
            "description": "Monte Carlo job enqueued"
        },
        401: {
            "model": ErrorResponseSchema,
            "description": "Invalid or missing authentication token",
        },
        404: {
            "model": ErrorResponseSchema, 
            "description": "Strategy or source backtest not found"
        },
    },
)
async def trigger_montecarlo(
    strategy_id: str,
    mc_data: MonteCarloRequestSchema,
    user: Annotated[dict, Depends(get_current_user)],
    montecarlo_service: MonteCarloService = Depends(get_montecarlo_service)
) -> JSONResponse:
    """Submit a Monte Carlo simulation job — consumes trades from an existing backtest (read-only)."""
    status_code, result = await montecarlo_service.trigger_montecarlo(
        user_id=user["user_id"],
        strategy_id=strategy_id,
        source_backtest_id=mc_data.source_backtest_id,
        simulation_count=mc_data.simulation_count,
        method=mc_data.method,
        random_seed=mc_data.random_seed,
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@strategy_router.get(
    "/{strategy_id}/montecarlos",
    dependencies=[Depends(security)],
    responses={
        200: {
            "model": SuccessResponseSchema[PaginatedMonteCarloRunsResponseSchema],
            "description": "Paginated list of Monte Carlo runs"
        },
        401: {
            "model": ErrorResponseSchema,
            "description": "Invalid or missing authentication token",
        },
    },
)
async def list_montecarlo_runs(
    strategy_id: str,
    user: Annotated[dict, Depends(get_current_user)],
    page: int = 1,
    limit: int = 8,
    search: str = "",
    montecarlo_service: MonteCarloService = Depends(get_montecarlo_service)
) -> JSONResponse:
    """List all Monte Carlo runs for a strategy with pagination."""
    status_code, result = await montecarlo_service.list_montecarlo_runs(
        user_id=user["user_id"], strategy_id=strategy_id, page=page, limit=limit, search=search
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@strategy_router.get(
    "/{strategy_id}/montecarlos/{run_id}",
    dependencies=[Depends(security)],
    responses={
        200: {
            "model": SuccessResponseSchema[MonteCarloRunResponseSchema],
            "description": "Monte Carlo run details with probability distributions"
        },
        401: {
            "model": ErrorResponseSchema,
            "description": "Invalid or missing authentication token",
        },
        404: {
            "model": ErrorResponseSchema, 
            "description": "Run not found"
        },
    },
)
async def get_montecarlo_run(
    strategy_id: str,
    run_id: str,
    user: Annotated[dict, Depends(get_current_user)],
    montecarlo_service: MonteCarloService = Depends(get_montecarlo_service)
) -> JSONResponse:
    """Fetch a specific Monte Carlo run with full statistical distribution summary."""
    status_code, result = await montecarlo_service.get_montecarlo_run(
        user_id=user["user_id"], strategy_id=strategy_id, run_id=run_id
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)
