import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.advices.base_response_handler import BaseResponseHandler
from app.advices.responses import ErrorResponseSchema, SuccessResponseSchema
from app.db.connect_db import get_db
from app.middlewares.auth_middleware import get_current_user

from ..repositories.user_repository import UserRepository
from ..schema.user_schema import GenericMessageSchema, UserSchema, UserUpdateSchema
from ..services.user_service import UserService

logger = logging.getLogger(__name__)

security = HTTPBearer()
user_router = APIRouter(prefix="/users", tags=["User Management"])


async def get_user_service(session: AsyncSession = Depends(get_db)) -> UserService:
    """
    Dependency to get the UserService instance.
    :param session: The database session.
    :return: An instance of UserService.
    """
    user_repository = UserRepository(session)
    return UserService(user_repository)


@user_router.get(
    "/me",
    dependencies=[Depends(security)],
    responses={
        200: {
            "model": SuccessResponseSchema[UserSchema],
            "description": "When user profile is retrieved successfully",
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
async def get_current_user(
    current_user: dict = Depends(get_current_user),
    user_service: UserService = Depends(get_user_service),
) -> JSONResponse:
    """
    Endpoint to get current user profile.
    :param current_user: The authenticated user information from dependency.
    :param user_service: The UserService instance to handle user operations.
    :return: JSONResponse with the status code and result.
    """
    current_user_id = current_user["user_id"]
    status_code, result = await user_service.get_user_profile(current_user_id)
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@user_router.put(
    "/me",
    dependencies=[Depends(security)],
    responses={
        200: {
            "model": SuccessResponseSchema[UserSchema],
            "description": "When user profile is updated successfully",
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
async def update_current_user(
    update_data: UserUpdateSchema,
    current_user: dict = Depends(get_current_user),
    user_service: UserService = Depends(get_user_service),
) -> JSONResponse:
    """
    Endpoint to update current user profile.
    :param update_data: The data to update.
    :param current_user: The authenticated user information from dependency.
    :param user_service: The UserService instance to handle user operations.
    :return: JSONResponse with the status code and result.
    """
    current_user_id = current_user["user_id"]
    status_code, result = await user_service.update_user_profile(
        current_user_id, **update_data.model_dump(exclude_unset=True)
    )
    return BaseResponseHandler.success_response(data=result, status_code=status_code)


@user_router.delete(
    "/me",
    dependencies=[Depends(security)],
    responses={
        200: {
            "model": SuccessResponseSchema[GenericMessageSchema],
            "description": "When user account is deleted successfully",
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
async def delete_current_user(
    current_user: dict = Depends(get_current_user),
    user_service: UserService = Depends(get_user_service),
) -> JSONResponse:
    """
    Endpoint to delete current user account.
    :param current_user: The authenticated user information from dependency.
    :param user_service: The UserService instance to handle user operations.
    :return: JSONResponse with the status code and result.
    """
    current_user_id = current_user["user_id"]
    status_code, result = await user_service.delete_user_account(current_user_id)
    return BaseResponseHandler.success_response(data=result, status_code=status_code)
