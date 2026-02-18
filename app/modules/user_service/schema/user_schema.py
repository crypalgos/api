from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

# Import session schemas for re-export
from .session_schema import SessionSchema, UserSessionsResponseSchema

__all__ = [
    "UserSchema",
    "UserUpdateSchema",
    "UserRegistrationSchema",
    "UserLoginSchema",
    "UserLoginResponseSchema",
    "UserRegistrationResponseSchema",
    "VerifyUserSchema",
    "CheckVerificationCodeSchema",
    "VerifyUserResponseSchema",
    "ForgotPasswordSchema",
    "ResetPasswordSchema",
    "ResendVerificationSchema",
    "RefreshTokenSchema",
    "GenericMessageSchema",
    "SessionSchema",
    "UserSessionsResponseSchema",
    "CheckUsernameAvailabilitySchema",
    "UsernameAvailabilityResponseSchema",
]


class UserSchema(BaseModel):
    id: str = Field(..., description="Unique identifier for the user")
    name: str = Field(..., description="Name of the registered user")
    email: str = Field(..., description="Email address of the registered user")
    username: str = Field(..., description="Username of the registered user")
    country_code: int | None = Field(
        None, description="Country code of the registered user"
    )
    phone: str | None = Field(None, description="Phone number of the registered user")
    is_verified: bool = Field(
        ..., description="Verification status of the registered user"
    )
    created_at: datetime = Field(..., description="Creation time of the user record")
    updated_at: datetime = Field(..., description="Last update time of the user record")

    class Config:
        from_attributes = True


class UserUpdateSchema(BaseModel):
    name: str | None = Field(
        None, min_length=2, max_length=50, description="Name of the user"
    )
    email: EmailStr | None = Field(None, description="Email address of the user")
    username: str | None = Field(
        None, min_length=3, max_length=50, description="Username for the user"
    )
    country_code: int | None = Field(None, description="Country code of the user")
    phone: str | None = Field(None, description="Phone number of the user")


class UserRegistrationSchema(BaseModel):
    name: str = Field(..., min_length=2, max_length=50, description="Name of the user")
    email: EmailStr = Field(..., description="Email address of the user")
    username: str = Field(
        ..., min_length=3, max_length=50, description="Username for the user"
    )
    password: str = Field(..., min_length=8, description="Password for the user")


class UserLoginSchema(BaseModel):
    identifier: str = Field(..., description="Email or username for login")
    password: str = Field(..., description="Password for login")


class UserLoginResponseSchema(BaseModel):
    user: UserSchema = Field(..., description="User details")
    access_token: str = Field(..., description="JWT access token")
    message: str = Field(default="Login successful", description="Success message")


class UserRegistrationResponseSchema(BaseModel):
    user: UserSchema = Field(..., description="Details of the registered user")
    message: str = Field(
        "User registered successfully. Please verify your email.",
        description="Success message for user registration",
    )


class VerifyUserSchema(BaseModel):
    identifier: str = Field(..., description="Email address or username of the user")
    verification_code: str = Field(..., description="Verification code sent to email")


class CheckVerificationCodeSchema(BaseModel):
    identifier: str = Field(..., description="Email address or username of the user")
    verification_code: str = Field(..., description="Verification code to check")


class VerifyUserResponseSchema(BaseModel):
    user: UserSchema = Field(..., description="User details")
    access_token: str = Field(..., description="Authentication tokens")
    message: str = Field(
        default="User verified and logged in successfully",
        description="Success message",
    )


class ForgotPasswordSchema(BaseModel):
    identifier: str = Field(..., description="Email address or username of the user")


class ResetPasswordSchema(BaseModel):
    identifier: str = Field(..., description="Email address or username of the user")
    verification_code: str = Field(..., description="Verification code sent to email")
    new_password: str = Field(..., min_length=8, description="New password")


class ResendVerificationSchema(BaseModel):
    identifier: str = Field(..., description="Email address or username of the user")


class RefreshTokenSchema(BaseModel):
    refresh_token: str = Field(
        ..., description="Refresh token for getting new access token"
    )


class GenericMessageSchema(BaseModel):
    message: str = Field(..., description="Generic message response")


class CheckUsernameAvailabilitySchema(BaseModel):
    username: str = Field(
        ..., min_length=3, max_length=50, description="Username to check availability"
    )


class UsernameAvailabilityResponseSchema(BaseModel):
    available: bool = Field(..., description="Whether the username is available")
    username: str = Field(..., description="The username that was checked")
    message: str = Field(..., description="Response message")
