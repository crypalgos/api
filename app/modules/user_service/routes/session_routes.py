import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.advices.responses import ErrorResponseSchema, SuccessResponseSchema
from app.db.connect_db import get_db
from app.middlewares.auth_middleware import get_current_user

from ..repositories.session_repository import SessionRepository
from ..repositories.user_repository import UserRepository
from ..services.session_service import SessionService

logger = logging.getLogger(__name__)

session_router = APIRouter(prefix="/sessions", tags=["Session Management"])
security = HTTPBearer()

from ..schema.user_schema import (  # noqa: E402
    GenericMessageSchema,
    UserSessionsResponseSchema,
)


async def get_session_service(
    session: AsyncSession = Depends(get_db),
) -> SessionService:
    """
    Dependency to get the SessionService instance.
    :param session: The database session.
    :return: An instance of SessionService.
    """
    session_repository = SessionRepository(session)
    user_repository = UserRepository(session)
    return SessionService(session_repository, user_repository)


async def get_current_user_data(
    request: Request,
    current_user: dict = Depends(get_current_user),
) -> tuple[str, str]:
    """
    Dependency to get current user ID and refresh token from authenticated user and cookies.
    :param request: The FastAPI request object to access cookies.
    :param current_user: The authenticated user information from dependency.
    :return: Tuple of (user_id, refresh_token).
    """
    user_id = current_user["user_id"]

    # Get refresh token from cookies
    refresh_token = request.cookies.get("refresh_token", "")

    return user_id, refresh_token


@session_router.get(
    "",
    dependencies=[Depends(security)],
    responses={
        200: {
            "model": SuccessResponseSchema[UserSessionsResponseSchema],
            "description": "When user sessions are retrieved successfully",
        },
        401: {
            "model": ErrorResponseSchema,
            "description": "Invalid or missing authentication token",
        },
        404: {
            "model": ErrorResponseSchema,
            "description": "User not found",
        },
    },
)
async def get_user_sessions(
    current_user_data: tuple[str, str] = Depends(get_current_user_data),
    session_service: SessionService = Depends(get_session_service),
) -> JSONResponse:
    """
    Endpoint to get all active sessions for the current user.
    :param current_user_data: The current user ID and refresh token from JWT token.
    :param session_service: The SessionService instance to handle session operations.
    :return: JSONResponse with the status code and result.
    """
    current_user_id, _ = current_user_data
    status_code, result = await session_service.get_user_sessions(current_user_id)
    return JSONResponse(
        status_code=status_code,
        content=SuccessResponseSchema(data=result).model_dump(mode="json"),
    )


@session_router.delete(
    "/{session_id}",
    dependencies=[Depends(security)],
    responses={
        200: {
            "model": SuccessResponseSchema[GenericMessageSchema],
            "description": "When session is deleted successfully",
        },
        401: {
            "model": ErrorResponseSchema,
            "description": "Invalid or missing authentication token",
        },
        404: {
            "model": ErrorResponseSchema,
            "description": "Session or user not found",
        },
    },
)
async def delete_session(
    session_id: str,
    current_user_data: tuple[str, str] = Depends(get_current_user_data),
    session_service: SessionService = Depends(get_session_service),
) -> JSONResponse:
    """
    Endpoint to delete a specific session for the current user.
    :param session_id: The session ID to delete.
    :param current_user_data: The current user ID and refresh token from JWT token.
    :param session_service: The SessionService instance to handle session operations.
    :return: JSONResponse with the status code and result.
    """
    current_user_id, current_refresh_token = current_user_data
    status_code, result = await session_service.delete_session(
        current_user_id, session_id, current_refresh_token
    )
    return JSONResponse(
        status_code=status_code,
        content=SuccessResponseSchema(data=result).model_dump(mode="json"),
    )


@session_router.delete(
    "",
    dependencies=[Depends(security)],
    responses={
        200: {
            "model": SuccessResponseSchema[GenericMessageSchema],
            "description": "When all other sessions are deleted successfully",
        },
        401: {
            "model": ErrorResponseSchema,
            "description": "Invalid or missing authentication token",
        },
        404: {
            "model": ErrorResponseSchema,
            "description": "User not found",
        },
    },
)
async def delete_all_sessions(
    current_user_data: tuple[str, str] = Depends(get_current_user_data),
    session_service: SessionService = Depends(get_session_service),
) -> JSONResponse:
    """
    Endpoint to delete all sessions except the current one (logout from all other devices).
    :param current_user_data: The current user ID and refresh token from JWT token.
    :param session_service: The SessionService instance to handle session operations.
    :return: JSONResponse with the status code and result.
    """
    current_user_id, current_refresh_token = current_user_data
    status_code, result = await session_service.delete_all_sessions(
        current_user_id, current_refresh_token
    )
    return JSONResponse(
        status_code=status_code,
        content=SuccessResponseSchema(data=result).model_dump(mode="json"),
    )
