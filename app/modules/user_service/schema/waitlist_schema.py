from datetime import datetime
from pydantic import BaseModel, EmailStr, Field

class WaitlistSignupSchema(BaseModel):
    name: str = Field(..., min_length=2, max_length=50, description="Full name of the waitlist subscriber")
    email: EmailStr = Field(..., description="Email address of the subscriber")

class WaitlistResponseSchema(BaseModel):
    id: str = Field(..., description="Unique ID of the waitlist entry")
    name: str = Field(..., description="Subscriber name")
    email: str = Field(..., description="Subscriber email")
    created_at: datetime = Field(..., description="Time of sign up")

    class Config:
        from_attributes = True
