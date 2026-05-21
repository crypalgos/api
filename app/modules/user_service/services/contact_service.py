import logging
from app.exceptions.exceptions import ResourceNotFoundException
from app.modules.user_service.models.contact_model import ContactMessage
from app.modules.user_service.repositories.contact_repository import ContactRepository
from app.modules.user_service.schema.contact_schema import ContactCreateSchema, ContactResponseSchema
from app.modules.user_service.schema.user_schema import GenericMessageSchema

logger = logging.getLogger(__name__)

class ContactService:
    def __init__(self, repository: ContactRepository):
        self.repository = repository

    async def create_message(self, data: ContactCreateSchema) -> tuple[int, ContactResponseSchema]:
        logger.info(f"Creating new contact message from {data.email}")
        new_msg = ContactMessage(
            name=data.name,
            email=data.email,
            subject=data.subject,
            message=data.message,
        )
        created_msg = await self.repository.create(new_msg)
        response_schema = ContactResponseSchema.model_validate(created_msg)
        return 201, response_schema

    async def get_all_messages(self, offset: int = 0, limit: int = 50, query: str = "") -> tuple[int, dict]:
        logger.info("Fetching contact messages")
        paginated_result = await self.repository.get_all_paginated(offset, limit, query)
        items = paginated_result.get("ContactMessage", [])
        mapped_items = [ContactResponseSchema.model_validate(item) for item in items]
        paginated_result["items"] = mapped_items
        paginated_result.pop("ContactMessage", None)
        return 200, paginated_result

    async def delete_message(self, message_id: str) -> tuple[int, GenericMessageSchema]:
        logger.info(f"Deleting contact message {message_id}")
        success = await self.repository.delete(message_id)
        if not success:
            raise ResourceNotFoundException("Contact message not found")
        return 200, GenericMessageSchema(message="Contact message deleted successfully")
