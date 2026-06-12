import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.advices.base_response_handler import BaseResponseHandler
from app.advices.responses import ErrorResponseSchema, SuccessResponseSchema
from app.db.connect_db import get_db
from app.middlewares.auth_middleware import get_admin_user
from app.modules.user_service.repositories.contact_repository import ContactRepository
from app.modules.user_service.schema.contact_schema import (
    ContactCreateSchema,
    ContactResponseSchema,
)
from app.modules.user_service.schema.user_schema import GenericMessageSchema
from app.modules.user_service.services.contact_service import ContactService

logger = logging.getLogger(__name__)

contact_router = APIRouter(prefix="/contact", tags=["Contact Management"])
security = HTTPBearer()

async def get_contact_service(session: AsyncSession = Depends(get_db)) -> ContactService:
    """
    Dependency to get the ContactService instance.
    :param session: The database session.
    :return: An instance of ContactService.
    """
    repository = ContactRepository(session)
    return ContactService(repository)

@contact_router.post(
    "",
    responses={
        201: {
            "model": SuccessResponseSchema[ContactResponseSchema],
            "description": "When a contact message is submitted successfully",
        },
        422: {
            "model": ErrorResponseSchema,
            "description": "Validation error for the contact message data",
        },
    },
)
async def create_contact_message(
    data: ContactCreateSchema,
    contact_service: ContactService = Depends(get_contact_service),
) -> JSONResponse:
    """
    Endpoint to submit a new contact message.
    """
    logger.info(f"Contact message submission attempt from: {data.email}")
    status_code, result = await contact_service.create_message(data)
    return BaseResponseHandler.success_response(data=result, status_code=status_code)

@contact_router.get(
    "",
    dependencies=[Depends(security)],
    responses={
        200: {
            "model": SuccessResponseSchema[dict],
            "description": "When contact messages are retrieved successfully",
        },
        401: {
            "model": ErrorResponseSchema,
            "description": "Invalid or missing admin authentication token",
        },
    },
)
async def get_contact_messages(
    offset: int = 0,
    limit: int = 50,
    query: str = "",
    admin_user: dict = Depends(get_admin_user),
    contact_service: ContactService = Depends(get_contact_service),
) -> JSONResponse:
    """
    Endpoint for admin to retrieve all contact messages.
    """
    logger.info("Admin retrieving contact messages")
    status_code, result = await contact_service.get_all_messages(offset, limit, query)
    return BaseResponseHandler.success_response(data=result, status_code=status_code)

@contact_router.delete(
    "/{id}",
    dependencies=[Depends(security)],
    responses={
        200: {
            "model": SuccessResponseSchema[GenericMessageSchema],
            "description": "When a contact message is deleted successfully",
        },
        401: {
            "model": ErrorResponseSchema,
            "description": "Invalid or missing admin authentication token",
        },
        404: {
            "model": ErrorResponseSchema,
            "description": "Contact message not found",
        },
    },
)
async def delete_contact_message(
    id: str,
    admin_user: dict = Depends(get_admin_user),
    contact_service: ContactService = Depends(get_contact_service),
) -> JSONResponse:
    """
    Endpoint for admin to delete a contact message.
    """
    logger.info(f"Admin deleting contact message: {id}")
    status_code, result = await contact_service.delete_message(id)
    return BaseResponseHandler.success_response(data=result, status_code=status_code)
