from datetime import datetime
from typing import Dict, Generic, Optional, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ApiErrorSchema(BaseModel):
    status_code: int = Field(..., description="Http status code")
    message: str = Field(..., description="Error message")
    errors: Optional[Dict[str, str]] = Field(
        None, description="Additional error details"
    )


class SuccessResponseSchema(BaseModel, Generic[T]):
    local_date_time: str = Field(
        default_factory=lambda: datetime.now().isoformat(),
        description="Local date and time of the response",
    )
    data: Optional[T] = None
    api_error: None = None


class ErrorResponseSchema(BaseModel):
    local_date_time: str = Field(
        default_factory=lambda: datetime.now().isoformat(),
        description="Local date and time of the response",
    )
    data: None = None
    api_error: ApiErrorSchema = Field(
        ..., description="Details of the error that occurred"
    )
