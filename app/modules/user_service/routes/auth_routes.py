import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response

from app.advices.base_response_handler import BaseResponseHandler
from app.advices.responses import ErrorResponseSchema, SuccessResponseSchema
from app.config.settings import settings
from app.db.connect_db import get_db
from app.exceptions.exceptions import UnauthorizedAccessException

from ..repositories.session_repository import SessionRepository
from ..repositories.user_repository import UserRepository
from ..services.auth_service import AuthService

logger = logging.getLogger(__name__)

auth_router = APIRouter(prefix="/auth", tags=["Authentication"])
from ..schema.user_schema import (  # noqa: E402
    CheckUsernameAvailabilitySchema,
    CheckVerificationCodeSchema,
    ForgotPasswordSchema,
    GenericMessageSchema,
    RefreshTokenSchema,
    ResendVerificationSchema,
    ResetPasswordSchema,
    UserLoginResponseSchema,
    UserLoginSchema,
    UsernameAvailabilityResponseSchema,
    UserRegistrationResponseSchema,
    UserRegistrationSchema,
    VerifyUserSchema,
)


def set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    """Set HTTP-only cookies for authentication tokens"""
    is_prod = settings.env == "production"
    cookie_samesite = "lax" if is_prod else "none"
    cookie_secure = True if (is_prod or cookie_samesite == "none") else False

    # Access token is non-HttpOnly in development to allow Bearer token fallback
    response.set_cookie(
        key="access_token",
        value=access_token,
        max_age=settings.access_token_expire_minutes * 60,  # Convert to seconds
        httponly=is_prod,
        secure=cookie_secure,
        samesite=cookie_samesite,
        path="/",
    )

    # Set refresh token cookie (long-lived)
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        max_age=settings.refresh_token_expire_minutes * 60,  # Convert to seconds
        httponly=True,
        secure=cookie_secure,
        samesite=cookie_samesite,
        path="/",  # Ensure cookie is available site-wide
    )




def clear_auth_cookies(response: Response) -> None:
    """Clear authentication cookies"""
    is_prod = settings.env == "production"
    cookie_samesite = "lax" if is_prod else "none"
    cookie_secure = True if (is_prod or cookie_samesite == "none") else False

    response.delete_cookie(
        key="access_token",
        path="/",
        samesite=cookie_samesite,
        secure=cookie_secure,
    )
    response.delete_cookie(
        key="refresh_token",
        path="/",
        samesite=cookie_samesite,
        secure=cookie_secure,
    )


async def get_auth_service(session: AsyncSession = Depends(get_db)) -> AuthService:
    """
    Dependency to get the AuthService instance.
    :param session: The database session.
    :return: An instance of AuthService.
    """
    user_repository = UserRepository(session)
    session_repository = SessionRepository(session)
    return AuthService(user_repository, session_repository)


def get_client_info(request: Request) -> tuple[str, str]:
    """Extract client information from request"""
    user_agent = request.headers.get("user-agent", "Unknown")
    ip_address = request.client.host if request.client else "Unknown"
    return user_agent, ip_address


@auth_router.post(
    "/register",
    responses={
        201: {
            "model": SuccessResponseSchema[UserRegistrationResponseSchema],
            "description": "When a new user is registered successfully",
        },
        200: {
            "model": SuccessResponseSchema[UserRegistrationResponseSchema],
            "description": "When a user is already registered and updated",
        },
        422: {
            "model": ErrorResponseSchema,
            "description": "Validation error for the user data",
        },
    },
)
async def register_user(
    user_data: UserRegistrationSchema,
    auth_service: AuthService = Depends(get_auth_service),
) -> JSONResponse:
    """
    Endpoint to register a new user or update an existing user.
    :param user_data: The user data to register or update.
    :param auth_service: The AuthService instance to handle user operations.
    :return: JSONResponse with the status code and result.
    """
    logger.info(f"User registration attempt: {user_data.email}")
    status_code, result = await auth_service.register_user(user_data)
    logger.info(f"User registration successful: {user_data.email}")
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@auth_router.post(
    "/check-username",
    responses={
        200: {
            "model": SuccessResponseSchema[UsernameAvailabilityResponseSchema],
            "description": "Username availability check result",
        },
        422: {
            "model": ErrorResponseSchema,
            "description": "Validation error for the username",
        },
    },
)
async def check_username_availability(
    username_data: CheckUsernameAvailabilitySchema,
    auth_service: AuthService = Depends(get_auth_service),
) -> JSONResponse:
    """
    Endpoint to check if a username is available.
    :param username_data: The username to check.
    :param auth_service: The AuthService instance to handle the check.
    :return: JSONResponse with availability status.
    """
    logger.info(f"Checking username availability: {username_data.username}")
    status_code, result = await auth_service.check_username_availability(
        username_data.username
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@auth_router.post(
    "/login",
    responses={
        200: {
            "model": SuccessResponseSchema[UserLoginResponseSchema],
            "description": "When user logs in successfully",
        },
        401: {
            "model": ErrorResponseSchema,
            "description": "Invalid credentials or unverified user",
        },
        422: {
            "model": ErrorResponseSchema,
            "description": "Validation error for the login data",
        },
    },
)
async def login_user(
    login_data: UserLoginSchema,
    request: Request,
    response: Response,
    auth_service: AuthService = Depends(get_auth_service),
) -> Response:
    """
    Endpoint to login a user with email/username and password.
    Sets HTTP-only cookies for access and refresh tokens.
    :param login_data: The login credentials.
    :param request: The request object to extract client info.
    :param auth_service: The AuthService instance to handle user operations.
    :return: JSONResponse with user data (tokens set as HTTP-only cookies).
    """
    user_agent, ip_address = get_client_info(request)
    logger.info(f"Login attempt: {login_data.identifier} from IP: {ip_address}")
    (
        status_code,
        access_token,
        refresh_token,
        expires_in,
        user_schema,
    ) = await auth_service.login_user(login_data, user_agent, ip_address)
    logger.info(f"Login successful: {login_data.identifier}")

    user_response = UserLoginResponseSchema(
        user=user_schema,
        access_token=access_token,
        message="Login successful",
    )

    # Create JSONResponse first
    json_response = BaseResponseHandler.success_response(
        data=user_response, status_code=status_code
    )

    # Convert to Response object and set cookies
    response = Response(
        content=json_response.body,
        status_code=json_response.status_code,
        media_type="application/json",
    )

    # Set HTTP-only cookies for tokens
    set_auth_cookies(response, access_token, refresh_token)

    return response


@auth_router.post(
    "/verify",
    responses={
        200: {
            "model": SuccessResponseSchema[UserLoginResponseSchema],
            "description": "When user is verified and logged in successfully",
        },
        400: {
            "model": ErrorResponseSchema,
            "description": "Invalid verification code or already verified",
        },
        404: {
            "model": ErrorResponseSchema,
            "description": "User not found",
        },
        422: {
            "model": ErrorResponseSchema,
            "description": "Validation error for the verification data",
        },
    },
)
async def verify_user(
    verify_data: VerifyUserSchema,
    request: Request,
    auth_service: AuthService = Depends(get_auth_service),
) -> Response:
    """
    Endpoint to verify user email and automatically log them in.
    Sets HTTP-only cookies for access and refresh tokens.
    :param verify_data: The verification data including email and code.
    :param request: The request object to extract client info.
    :param auth_service: The AuthService instance to handle user operations.
    :return: JSONResponse with user data (tokens set as HTTP-only cookies).
    """
    user_agent, ip_address = get_client_info(request)
    status_code, result = await auth_service.verify_user(
        verify_data, user_agent, ip_address
    )

    # Return user data with access token (refresh token only in cookie)
    user_response = UserLoginResponseSchema(
        user=result.user,
        access_token=result.tokens["access_token"],
        message=result.message,
    )

    # Create JSONResponse first
    json_response = BaseResponseHandler.success_response(
        data=user_response, status_code=status_code
    )

    # Convert to Response object and set cookies
    response = Response(
        content=json_response.body,
        status_code=json_response.status_code,
        media_type="application/json",
    )

    # Set HTTP-only cookies for tokens
    set_auth_cookies(
        response, result.tokens["access_token"], result.tokens["refresh_token"]
    )

    return response


@auth_router.post(
    "/check-verification-code",
    responses={
        200: {
            "model": SuccessResponseSchema[GenericMessageSchema],
            "description": "When verification code is valid",
        },
        400: {
            "model": ErrorResponseSchema,
            "description": "Invalid verification code, expired, or already verified",
        },
        404: {
            "model": ErrorResponseSchema,
            "description": "User not found",
        },
        422: {
            "model": ErrorResponseSchema,
            "description": "Validation error for the verification data",
        },
    },
)
async def check_verification_code(
    check_data: CheckVerificationCodeSchema,
    auth_service: AuthService = Depends(get_auth_service),
) -> JSONResponse:
    """
    Endpoint to check if verification code is valid without verifying the user.
    Useful for frontend validation.
    :param check_data: The verification data including email and code.
    :param auth_service: The AuthService instance to handle user operations.
    :return: JSONResponse with validation result.
    """
    status_code, result = await auth_service.check_verification_code(
        check_data.identifier, check_data.verification_code
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@auth_router.post(
    "/refresh",
    responses={
        200: {
            "model": SuccessResponseSchema[UserLoginResponseSchema],
            "description": "When access token is refreshed successfully",
        },
        401: {
            "model": ErrorResponseSchema,
            "description": "Invalid or expired refresh token",
        },
    },
)
async def refresh_token(
    request: Request,
    auth_service: AuthService = Depends(get_auth_service),
) -> Response:
    """
    Endpoint to refresh access token using refresh token from HTTP-only cookie.
    Sets new access token as HTTP-only cookie and returns user + token info.
    :param request: The request object to extract cookies.
    :param auth_service: The AuthService instance to handle user operations.
    :return: JSONResponse with user data and new access token.
    """
    # Extract refresh token from HTTP-only cookie
    refresh_token = request.cookies.get("refresh_token")

    if not refresh_token:
        raise UnauthorizedAccessException("Refresh token not found")

    # Create refresh data from cookie (internal use only)
    refresh_data = RefreshTokenSchema(refresh_token=refresh_token)
    status_code, result = await auth_service.refresh_token(refresh_data)

    # Import UserSchema to convert user model
    from ..schema.user_schema import UserSchema

    # Return user data and new access token in response
    token_response = UserLoginResponseSchema(
        user=UserSchema.model_validate(result["user"]),
        access_token=result["access_token"],
        message="Access token refreshed successfully",
    )

    # Create JSONResponse first
    json_response = BaseResponseHandler.success_response(
        data=token_response, status_code=status_code
    )

    # Convert to Response object and set new access token cookie
    response = Response(
        content=json_response.body,
        status_code=json_response.status_code,
        headers=dict(json_response.headers),
        media_type="application/json",
    )

    # Set HTTP-only cookies for tokens
    set_auth_cookies(response, result["access_token"], refresh_token)

    return response


@auth_router.post(
    "/forgot-password",
    responses={
        200: {
            "model": SuccessResponseSchema[GenericMessageSchema],
            "description": "Password reset code sent if email exists",
        },
        422: {
            "model": ErrorResponseSchema,
            "description": "Validation error for the email",
        },
    },
)
async def forgot_password(
    forgot_data: ForgotPasswordSchema,
    auth_service: AuthService = Depends(get_auth_service),
) -> JSONResponse:
    """
    Endpoint to request password reset.
    :param forgot_data: The email for password reset.
    :param auth_service: The AuthService instance to handle user operations.
    :return: JSONResponse with the status code and result.
    """
    status_code, result = await auth_service.forgot_password(forgot_data)
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@auth_router.post(
    "/reset-password",
    responses={
        200: {
            "model": SuccessResponseSchema[GenericMessageSchema],
            "description": "When password is reset successfully",
        },
        400: {
            "model": ErrorResponseSchema,
            "description": "Invalid verification code or expired",
        },
        404: {
            "model": ErrorResponseSchema,
            "description": "User not found",
        },
        422: {
            "model": ErrorResponseSchema,
            "description": "Validation error for the reset data",
        },
    },
)
async def reset_password(
    reset_data: ResetPasswordSchema,
    auth_service: AuthService = Depends(get_auth_service),
) -> JSONResponse:
    """
    Endpoint to reset password using verification code.
    :param reset_data: The password reset data including email, code, and new password.
    :param auth_service: The AuthService instance to handle user operations.
    :return: JSONResponse with the status code and result.
    """
    status_code, result = await auth_service.reset_password(reset_data)
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@auth_router.post(
    "/resend-verification",
    responses={
        200: {
            "model": SuccessResponseSchema[GenericMessageSchema],
            "description": "Verification code sent if email exists",
        },
        400: {
            "model": ErrorResponseSchema,
            "description": "User is already verified",
        },
        422: {
            "model": ErrorResponseSchema,
            "description": "Validation error for the email",
        },
    },
)
async def resend_verification_code(
    resend_data: ResendVerificationSchema,
    auth_service: AuthService = Depends(get_auth_service),
) -> JSONResponse:
    """
    Endpoint to resend verification code.
    :param resend_data: The email to resend verification code to.
    :param auth_service: The AuthService instance to handle user operations.
    :return: JSONResponse with the status code and result.
    """
    status_code, result = await auth_service.resend_verification_code(resend_data)
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@auth_router.post(
    "/logout",
    responses={
        200: {
            "model": SuccessResponseSchema[GenericMessageSchema],
            "description": "When user is logged out successfully",
        },
    },
)
async def logout_user(
    request: Request,
    auth_service: AuthService = Depends(get_auth_service),
) -> Response:
    """
    Endpoint to logout user by deleting session and clearing cookies.
    :param request: The request object to extract cookies.
    :param refresh_token: The refresh token from HTTP-only cookie.
    :param auth_service: The AuthService instance to handle user operations.
    :return: JSONResponse with the status code and result.
    """
    # Try to get refresh token from cookie if not provided
    refresh_token = request.cookies.get("refresh_token")

    if refresh_token:
        status_code, result = await auth_service.logout_user(refresh_token)
    else:
        result = GenericMessageSchema(message="Logged out successfully")
        status_code = 200

    # Create JSONResponse first
    json_response = BaseResponseHandler.success_response(
        data=result, status_code=status_code
    )

    # Convert to Response object and clear cookies
    response = Response(
        content=json_response.body,
        status_code=json_response.status_code,
        headers=dict(json_response.headers),
        media_type="application/json",
    )

    # Clear authentication cookies
    clear_auth_cookies(response)

    return response
