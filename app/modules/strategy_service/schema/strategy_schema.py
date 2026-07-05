from datetime import datetime
from enum import StrEnum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator

# ─────────────────────────────────────────────────────────────────────────────
# Shared Enums — the only source of run status/type strings (never literals)
# ─────────────────────────────────────────────────────────────────────────────


class JobStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    RETRYING = "RETRYING"


class RunType(StrEnum):
    BACKTEST = "BACKTEST"
    OPTIMIZATION = "OPTIMIZATION"
    WALKFORWARD = "WALKFORWARD"
    MONTECARLO = "MONTECARLO"


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
    version: int = 0
    strategy_type: str = "VISUAL"
    source_code: Optional[str] = None
    compiled_hash: Optional[str] = None
    current_version: int = 0
    has_unpublished_changes: bool = True

    created_at: datetime
    updated_at: datetime
    compile_error: Optional[str] = None
    compile_diagnostics: Optional[List[Dict[str, Any]]] = None

    is_golden: Optional[bool] = False
    latest_metrics: Optional[Dict[str, Any]] = None
    equity_preview: Optional[List[List[float]]] = None
    research_counts: Optional[Dict[str, int]] = None

    class Config:
        from_attributes = True

    @model_validator(mode="before")
    @classmethod
    def set_defaults(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if data.get("strategy_type") is None:
                data["strategy_type"] = "VISUAL"
            if data.get("current_version") is None:
                data["current_version"] = 0
            if data.get("has_unpublished_changes") is None:
                data["has_unpublished_changes"] = True
            if data.get("version") is None:
                data["version"] = data.get("current_version", 0) or 0
        else:
            if getattr(data, "strategy_type", None) is None:
                try:
                    data.strategy_type = "VISUAL"
                except AttributeError:
                    pass
            if getattr(data, "current_version", None) is None:
                try:
                    data.current_version = 0
                except AttributeError:
                    pass
            if getattr(data, "has_unpublished_changes", None) is None:
                try:
                    data.has_unpublished_changes = True
                except AttributeError:
                    pass
        return data


class StrategyVersionResponseSchema(BaseModel):
    id: str
    strategy_id: str
    version: int
    commit_message: Optional[str] = None
    canvas_json: Optional[Dict[str, Any]] = None
    source_code: Optional[str] = None
    compiled_code: str
    compiled_hash: str
    is_code_modified: bool
    label: Optional[str] = None
    approval_status: str = "DRAFT"
    is_golden: bool = False
    created_at: datetime

    class Config:
        from_attributes = True


class SaveVersionRequestSchema(BaseModel):
    commit_message: Optional[str] = None


class VersionDiffResponseSchema(BaseModel):
    diff_code: str
    canvas_changed: bool


class UpdateVersionLabelRequestSchema(BaseModel):
    label: Optional[str] = None


class UpdateVersionApprovalRequestSchema(BaseModel):
    approval_status: str


class ResearchNoteCreateSchema(BaseModel):
    content: str
    run_id: Optional[str] = None


class ResearchNoteResponseSchema(BaseModel):
    id: str
    strategy_id: str
    run_id: Optional[str] = None
    content: str
    created_at: datetime

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
    type: str = "int"  # "int", "float", "categorical", "bool"
    min_val: Optional[float] = None
    max_val: Optional[float] = None
    step: Optional[float] = None
    choices: Optional[List[Any]] = None


class ConstraintSchema(BaseModel):
    metric: str
    operator: str  # ">", "<", ">=", "<="
    value: float


class OptimizationRequestSchema(BaseModel):
    start_date: datetime
    end_date: datetime
    parameter_space: List[ParameterDefinitionSchema] = Field(..., min_length=1)
    objective: str = "sharpe_ratio"
    search_type: str = "grid"  # "grid" or "random"
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
    window_type: str = "rolling"  # "rolling" or "expanding"


class MonteCarloRequestSchema(BaseModel):
    source_backtest_id: str
    simulation_count: int = Field(default=10000, ge=100, le=100000)
    method: str = (
        "BOOTSTRAP"  # BOOTSTRAP, TRADE_SHUFFLE, RETURN_PERTURBATION, BLOCK_BOOTSTRAP
    )
    random_seed: Optional[int] = None


# ─────────────────────────────────────────────────────────────────────────────
# Unified Research Run Responses
# ─────────────────────────────────────────────────────────────────────────────


class ResearchRunResponseSchema(BaseModel):
    id: str
    strategy_id: str
    run_type: str = Field(..., alias="type")
    strategy_version_id: Optional[str] = None
    run_hash: Optional[str] = None
    artifact_size_bytes: Optional[int] = None
    compiled_hash: Optional[str] = None
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
    parent_run_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
        populate_by_name = True


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
