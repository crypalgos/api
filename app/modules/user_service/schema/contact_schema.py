from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class ContactCreateSchema(BaseModel):
    name: str = Field(
        ..., min_length=2, max_length=50, description="Name of the person contacting us"
    )
    email: EmailStr = Field(..., description="Email address of the sender")
    subject: str | None = Field(
        None, max_length=150, description="Subject of the message"
    )
    message: str = Field(
        ..., min_length=10, description="Content of the contact message"
    )


class ContactResponseSchema(BaseModel):
    id: str = Field(..., description="Unique ID of the contact message")
    name: str = Field(..., description="Sender's name")
    email: str = Field(..., description="Sender's email")
    subject: str | None = Field(None, description="Message subject")
    message: str = Field(..., description="Message content")
    created_at: datetime = Field(..., description="Time of message submission")

    class Config:
        from_attributes = True
