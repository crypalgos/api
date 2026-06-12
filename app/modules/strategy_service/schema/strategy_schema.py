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
    is_template: bool
    is_archived: bool
    created_at: datetime
    updated_at: datetime
    compile_error: Optional[str] = None
    compile_diagnostics: Optional[List[Dict[str, Any]]] = None

    class Config:
        from_attributes = True

class SaveCodeRequestSchema(BaseModel):
    code: str

class UpdateCanvasRequestSchema(BaseModel):
    canvas_json: Dict[str, Any]
    name: Optional[str] = None
    description: Optional[str] = None

class PaginatedStrategiesResponseSchema(BaseModel):
    total: int
    strategies: List[StrategyResponseSchema]
    current_page: int
    limit: int
    total_pages: int


# ─────────────────────────────────────────────────────────────────────────────
# Trigger Request Schemas (Remain Specific to Each Engine Input)
# ─────────────────────────────────────────────────────────────────────────────

class BacktestTriggerRequestSchema(BaseModel):
    start_date: datetime
    end_date: datetime
    initial_capital: float = 10000.0


class ParameterDefinitionSchema(BaseModel):
    name: str
    type: str = "int"                       # "int", "float", "categorical", "bool"
    min_val: Optional[float] = None
    max_val: Optional[float] = None
    step: Optional[float] = None
    choices: Optional[List[Any]] = None

class ConstraintSchema(BaseModel):
    metric: str
    operator: str                           # ">", "<", ">=", "<="
    value: float

class OptimizationRequestSchema(BaseModel):
    start_date: datetime
    end_date: datetime
    parameter_space: List[ParameterDefinitionSchema] = Field(..., min_length=1)
    objective: str = "sharpe_ratio"
    search_type: str = "grid"              # "grid" or "random"
    max_runs: int = Field(default=500, ge=1, le=5000)
    constraints: Optional[List[ConstraintSchema]] = None
    initial_capital: float = 10000.0


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


class MonteCarloRequestSchema(BaseModel):
    source_backtest_id: str
    simulation_count: int = Field(default=10000, ge=100, le=100000)
    method: str = "BOOTSTRAP"               # BOOTSTRAP, TRADE_SHUFFLE, RETURN_PERTURBATION, BLOCK_BOOTSTRAP
    random_seed: Optional[int] = None


# ─────────────────────────────────────────────────────────────────────────────
# Unified Research Run Responses
# ─────────────────────────────────────────────────────────────────────────────

class ResearchRunResponseSchema(BaseModel):
    id: str
    strategy_id: str
    type: str
    name: str
    description: Optional[str] = None
    is_favorite: bool
    status: str
    progress_percent: int
    report_version: Optional[str] = None
    metadata_s3_key: Optional[str] = None
    report_s3_key: Optional[str] = None
    dataset_s3_key: Optional[str] = None
    summary_json: Optional[Dict[str, Any]] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class ResearchRunTriggerResponseSchema(BaseModel):
    run_id: str
    task_id: str
    status: str
    message: str

class PaginatedResearchRunsResponseSchema(BaseModel):
    total: int
    runs: List[ResearchRunResponseSchema]
    current_page: int
    limit: int
    total_pages: int

class EditResearchRunRequestSchema(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None

class FavoriteResearchRunRequestSchema(BaseModel):
    is_favorite: bool


# ─────────────────────────────────────────────────────────────────────────────
# Progress & Latest Results
# ─────────────────────────────────────────────────────────────────────────────

class ResearchRunProgressResponseSchema(BaseModel):
    status: str
    progress_percent: int
    processed_candles: Optional[int] = None
    total_candles: Optional[int] = None
    completed_combinations: Optional[int] = None
    total_combinations: Optional[int] = None
    completed_windows: Optional[int] = None
    total_windows: Optional[int] = None
    completed_simulations: Optional[int] = None
    total_simulations: Optional[int] = None


class TemplateLibraryItemSchema(BaseModel):
    strategy_id: str
    strategy_name: str
    description: Optional[str] = None
    latest_backtest: Optional[Dict[str, Any]] = None
    latest_optimization: Optional[Dict[str, Any]] = None
    latest_walkforward: Optional[Dict[str, Any]] = None
    latest_montecarlo: Optional[Dict[str, Any]] = None
