from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel


class ConditionExpression(BaseModel):
    logical_gate: Optional[str] = None
    leftOperand: str
    operator: str
    rightOperand: str

class ConditionNodeDataSchema(BaseModel):
    expressions: list[ConditionExpression] = []

class ActionSequenceStep(BaseModel):
    actionType: str
    side: Optional[str] = None
    amount: Optional[float] = None
    sl: Optional[float] = None
    tp: Optional[float] = None
    limit_price: Optional[float] = None
    percentage: Optional[float] = None

class ActionNodeDataSchema(BaseModel):
    steps: list[ActionSequenceStep] = []

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

class BacktestTriggerRequestSchema(BaseModel):
    start_date: datetime
    end_date: datetime
    initial_capital: float = 10000.0

class BacktestResponseSchema(BaseModel):
    id: str
    strategy_id: str
    exchange: str
    symbol: str
    start_date: datetime
    end_date: datetime
    initial_capital: float
    leverage: int
    metrics_json: Dict[str, Any]
    charting_json: Dict[str, Any]
    created_at: datetime

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
