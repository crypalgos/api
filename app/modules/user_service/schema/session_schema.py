from datetime import datetime

from pydantic import BaseModel, Field


class SessionSchema(BaseModel):
    id: str = Field(..., description="Session ID")
    user_agent: str | None = Field(None, description="User agent string")
    ip_address: str | None = Field(None, description="IP address")
    created_at: datetime = Field(..., description="Session creation time")
    expires_at: datetime = Field(..., description="Session expiration time")

    class Config:
        from_attributes = True


class UserSessionsResponseSchema(BaseModel):
    sessions: list[SessionSchema] = Field(..., description="List of user sessions")
    total_sessions: int = Field(..., description="Total number of sessions")
    message: str = Field(
        default="Sessions retrieved successfully", description="Success message"
    )
