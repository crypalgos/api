from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ─────────────────────────────────────────────────────────────────────────────
# Shared Enums
# ─────────────────────────────────────────────────────────────────────────────

class JobStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    RETRYING = "RETRYING"


# ─────────────────────────────────────────────────────────────────────────────
# Strategy Schemas
# ─────────────────────────────────────────────────────────────────────────────



class StrategyCreateSchema(BaseModel):
    name: str
    description: Optional[str] = None
    canvas_json: Dict[str, Any]

class StrategyResponseSchema(BaseModel):
    id: str
    user_id: str
    name: str
    description: Optional[str]
    canvas_json: Dict[str, Any]
    compiled_code: str
    is_code_modified: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class SaveCodeRequestSchema(BaseModel):
    code: str

class UpdateCanvasRequestSchema(BaseModel):
    canvas_json: Dict[str, Any]
    name: Optional[str] = None
    description: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────────
# Backtest Schemas
# ─────────────────────────────────────────────────────────────────────────────

class BacktestTriggerRequestSchema(BaseModel):
    start_date: datetime
    end_date: datetime
    initial_capital: float = 10000.0

class BacktestResponseSchema(BaseModel):
    id: str
    strategy_id: str
    start_date: datetime
    end_date: datetime
    initial_capital: float
    status: str
    metrics_json: Optional[Dict[str, Any]] = None
    charting_json: Optional[Dict[str, Any]] = None
    progress_json: Optional[Dict[str, Any]] = None
    credits_used: int
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class BacktestTriggerResponseSchema(BaseModel):
    status: str
    task_id: str
    message: str

class PaginatedStrategiesResponseSchema(BaseModel):
    total: int
    strategies: list[StrategyResponseSchema]
    current_page: int
    limit: int
    total_pages: int

class PaginatedBacktestsResponseSchema(BaseModel):
    total: int
    backtests: list[BacktestResponseSchema]
    current_page: int
    limit: int
    total_pages: int


# ─────────────────────────────────────────────────────────────────────────────
# Optimization Schemas
# ─────────────────────────────────────────────────────────────────────────────

class ParameterDefinitionSchema(BaseModel):
    """Single parameter search dimension for optimization."""
    name: str
    type: str = "int"                       # "int", "float", "categorical"
    min_val: Optional[float] = None
    max_val: Optional[float] = None
    step: Optional[float] = None
    choices: Optional[List[Any]] = None     # For categorical params

class ConstraintSchema(BaseModel):
    metric: str                             # e.g. "max_drawdown"
    operator: str                           # ">", "<", ">=", "<="
    value: float

class OptimizationRequestSchema(BaseModel):
    start_date: datetime
    end_date: datetime
    parameter_space: List[ParameterDefinitionSchema] = Field(..., min_length=1)
    objective: str = "sharpe_ratio"         # Metric to maximize
    search_type: str = "grid"              # "grid" or "random"
    max_runs: int = Field(default=500, ge=1, le=5000)
    constraints: Optional[List[ConstraintSchema]] = None
    initial_capital: float = 10000.0

class OptimizationTriggerResponseSchema(BaseModel):
    run_id: str
    task_id: str
    status: JobStatus
    message: str

class OptimizationRunResponseSchema(BaseModel):
    id: str
    strategy_id: str
    status: JobStatus
    search_type: str
    objective: str
    max_runs: int
    initial_capital: float
    parameter_space_json: List[Any]
    constraints_json: Optional[List[Any]]
    best_result_json: Optional[Dict[str, Any]]
    leaderboard_json: Optional[List[Any]]
    progress_json: Optional[Dict[str, Any]]
    error_message: Optional[str]
    credits_used: int
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True

class PaginatedOptimizationRunsResponseSchema(BaseModel):
    total: int
    runs: List[OptimizationRunResponseSchema]
    current_page: int
    limit: int
    total_pages: int


# ─────────────────────────────────────────────────────────────────────────────
# Walk Forward Schemas
# ─────────────────────────────────────────────────────────────────────────────

class WalkForwardRequestSchema(BaseModel):
    start_date: datetime
    end_date: datetime
    train_period_months: int = Field(default=6, ge=1, le=60)
    test_period_months: int = Field(default=2, ge=1, le=24)
    step_months: int = Field(default=2, ge=1, le=12)
    objective: str = "sharpe_ratio"
    parameter_space: List[ParameterDefinitionSchema] = Field(..., min_length=1)
    constraints: Optional[List[ConstraintSchema]] = None
    initial_capital: float = 10000.0
    window_type: str = "rolling"            # "rolling" or "expanding"

class WalkForwardTriggerResponseSchema(BaseModel):
    run_id: str
    task_id: str
    status: JobStatus
    message: str

class WalkForwardRunResponseSchema(BaseModel):
    id: str
    strategy_id: str
    status: JobStatus
    window_type: str
    objective: str
    initial_capital: float
    window_config_json: Dict[str, Any]
    summary_json: Optional[Dict[str, Any]]
    progress_json: Optional[Dict[str, Any]]
    error_message: Optional[str]
    credits_used: int
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True

class PaginatedWalkForwardRunsResponseSchema(BaseModel):
    total: int
    runs: List[WalkForwardRunResponseSchema]
    current_page: int
    limit: int
    total_pages: int


# ─────────────────────────────────────────────────────────────────────────────
# Monte Carlo Schemas
# ─────────────────────────────────────────────────────────────────────────────

class MonteCarloRequestSchema(BaseModel):
    source_backtest_id: str                         # Existing backtest to draw trades from
    simulation_count: int = Field(default=10000, ge=100, le=100000)
    method: str = "BOOTSTRAP"                       # BOOTSTRAP, TRADE_SHUFFLE, RETURN_PERTURBATION, BLOCK_BOOTSTRAP
    random_seed: Optional[int] = None

class MonteCarloTriggerResponseSchema(BaseModel):
    run_id: str
    task_id: str
    status: JobStatus
    message: str

class MonteCarloRunResponseSchema(BaseModel):
    id: str
    strategy_id: str
    source_backtest_id: str
    status: JobStatus
    simulation_count: int
    method: str
    random_seed: Optional[int]
    summary_json: Optional[Dict[str, Any]]
    progress_json: Optional[Dict[str, Any]]
    error_message: Optional[str]
    credits_used: int
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True

class PaginatedMonteCarloRunsResponseSchema(BaseModel):
    total: int
    runs: List[MonteCarloRunResponseSchema]
    current_page: int
    limit: int
    total_pages: int
