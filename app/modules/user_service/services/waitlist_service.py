import logging
from app.exceptions.exceptions import ResourceAlreadyExistsException, ResourceNotFoundException
from app.modules.user_service.models.waitlist_model import Waitlist
from app.modules.user_service.repositories.waitlist_repository import WaitlistRepository
from app.modules.user_service.schema.waitlist_schema import WaitlistSignupSchema, WaitlistResponseSchema
from app.modules.user_service.schema.user_schema import GenericMessageSchema

logger = logging.getLogger(__name__)

class WaitlistService:
    def __init__(self, repository: WaitlistRepository):
        self.repository = repository

    async def join_waitlist(self, data: WaitlistSignupSchema) -> tuple[int, WaitlistResponseSchema]:
        logger.info(f"Adding email to waitlist: {data.email}")
        existing = await self.repository.get_by_field("email", data.email)
        if existing:
            raise ResourceAlreadyExistsException("This email is already registered on the waitlist.")
        
        new_entry = Waitlist(
            name=data.name,
            email=data.email,
        )
        created = await self.repository.create(new_entry)
        response = WaitlistResponseSchema.model_validate(created)
        return 201, response

    async def get_all_waitlist(self, offset: int = 0, limit: int = 50, query: str = "") -> tuple[int, dict]:
        logger.info("Fetching waitlist list")
        paginated_result = await self.repository.get_all_paginated(offset, limit, query)
        items = paginated_result.get("Waitlist", [])
        mapped_items = [WaitlistResponseSchema.model_validate(item) for item in items]
        paginated_result["items"] = mapped_items
        paginated_result.pop("Waitlist", None)
        return 200, paginated_result

    async def delete_waitlist_by_email(self, email: str) -> tuple[int, GenericMessageSchema]:
        logger.info(f"Deleting waitlist entry for email {email}")
        entry = await self.repository.get_by_field("email", email)
        if not entry:
            raise ResourceNotFoundException("Waitlist entry not found")
        await self.repository.delete(entry.id)
        return 200, GenericMessageSchema(message="Waitlist entry deleted successfully")
