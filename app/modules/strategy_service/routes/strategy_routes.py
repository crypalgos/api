import logging
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.advices.base_response_handler import BaseResponseHandler
from app.advices.responses import ErrorResponseSchema, SuccessResponseSchema
from app.db.connect_db import get_db
from app.middlewares.auth_middleware import get_current_user
from app.modules.strategy_service.repositories.backtest_repository import (
    BacktestRepository,
)

# Service & Repository imports
from app.modules.strategy_service.repositories.strategy_repository import (
    StrategyRepository,
)
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
)
from app.modules.strategy_service.services.strategy_service import StrategyService
from app.modules.strategy_service.tasks import run_asynchronous_backtest_task

logger = logging.getLogger(__name__)

strategy_router = APIRouter(prefix="/strategies", tags=["Strategies"])

async def get_strategy_service(session: AsyncSession = Depends(get_db)) -> StrategyService:
    strat_repo = StrategyRepository(session)
    bt_repo = BacktestRepository(session)
    return StrategyService(strat_repo, bt_repo)

@strategy_router.post(
    "",
    responses={
        201: {
            "model": SuccessResponseSchema[StrategyResponseSchema],
            "description": "Visual strategy canvas successfully created",
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
    responses={
        200: {
            "model": SuccessResponseSchema[PaginatedStrategiesResponseSchema],
            "description": "Successfully listed paginated strategies belonging to the user",
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
    responses={
        200: {
            "model": SuccessResponseSchema[StrategyResponseSchema],
            "description": "Successfully retrieved target strategy",
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
    responses={
        200: {
            "model": SuccessResponseSchema[dict],
            "description": "Successfully saved Monaco code modification, visual flow desynchronized",
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
    responses={
        200: {
            "model": SuccessResponseSchema[StrategyResponseSchema],
            "description": "Canvas saved and recompiled to Python successfully",
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
    responses={
        200: {
            "model": SuccessResponseSchema[StrategyResponseSchema],
            "description": "Successfully reset code custom changes back to visual canvas sync status",
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
    responses={
        202: {
            "model": SuccessResponseSchema[BacktestTriggerResponseSchema],
            "description": "Backtest enqueued successfully",
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
    strategy_service: StrategyService = Depends(get_strategy_service)
) -> JSONResponse:
    """Run an institutional-grade simulation backtest asynchronously in a background sandbox."""
    status_code, result = await strategy_service.trigger_backtest(
        user_id=user["user_id"],
        strategy_id=strategy_id,
        start_date=bt_data.start_date,
        end_date=bt_data.end_date,
        initial_capital=bt_data.initial_capital,
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)

@strategy_router.delete(
    "/{strategy_id}",
    responses={
        200: {
            "model": SuccessResponseSchema[dict],
            "description": "Strategy permanently deleted",
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
    responses={
        200: {
            "model": SuccessResponseSchema[PaginatedBacktestsResponseSchema],
            "description": "List all paginated backtest runs for a given strategy",
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
    exchange: str | None = None,
    symbol: str | None = None,
    strategy_service: StrategyService = Depends(get_strategy_service)
) -> JSONResponse:
    """List historical backtest results for a specific strategy with pagination and filtering."""
    status_code, result = await strategy_service.list_backtests(
        user_id=user["user_id"],
        strategy_id=strategy_id,
        page=page,
        limit=limit,
        exchange=exchange,
        symbol=symbol
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)

@strategy_router.get(
    "/{strategy_id}/backtests/{backtest_id}",
    responses={
        200: {
            "model": SuccessResponseSchema[BacktestResponseSchema],
            "description": "Successfully retrieved target backtest run with curves intact",
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
    strategy_service: StrategyService = Depends(get_strategy_service)
) -> JSONResponse:
    """Fetch a specific backtest run with full detailed curves and performance logs."""
    status_code, result = await strategy_service.get_backtest(
        user_id=user["user_id"],
        strategy_id=strategy_id,
        backtest_id=backtest_id
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)

@strategy_router.delete(
    "/{strategy_id}/backtests/{backtest_id}",
    responses={
        200: {
            "model": SuccessResponseSchema[dict],
            "description": "Backtest run deleted successfully",
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
    strategy_service: StrategyService = Depends(get_strategy_service)
) -> JSONResponse:
    """Permanently delete a specific backtest run."""
    status_code, result = await strategy_service.delete_backtest(
        user_id=user["user_id"],
        strategy_id=strategy_id,
        backtest_id=backtest_id
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)
