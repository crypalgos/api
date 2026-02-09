import logging
from typing import Any

from app.exceptions.exceptions import ResourceNotFoundException
from app.modules.user_service.repositories.user_repository import UserRepository

from ..schema.user_schema import GenericMessageSchema, UserSchema

logger = logging.getLogger(__name__)


class UserService:
    def __init__(self, user_repository: UserRepository):
        self.user_repository = user_repository

    async def get_user_profile(self, user_id: str) -> tuple[int, UserSchema]:
        """Get user profile by user ID"""
        logger.info(f"Fetching profile for user: {user_id}")
        user = await self.user_repository.get_by_id(user_id)
        if not user:
            logger.warning(f"User not found: {user_id}")
            raise ResourceNotFoundException("User not found")

        user_schema = UserSchema.model_validate(user)
        return 200, user_schema

    async def delete_user_account(
        self, user_id: str
    ) -> tuple[int, GenericMessageSchema]:
        """Delete user account and all associated data"""
        logger.info(f"Deleting account for user: {user_id}")
        user = await self.user_repository.get_by_id(user_id)
        if not user:
            logger.warning(f"User not found: {user_id}")
            raise ResourceNotFoundException("User not found")

        # Delete the user (this will cascade delete sessions due to relationship)
        await self.user_repository.delete_user(user_id)

        return 200, GenericMessageSchema(message="User account deleted successfully")

    async def update_user_profile(
        self, user_id: str, **update_data: Any
    ) -> tuple[int, UserSchema]:
        """Update user profile"""
        logger.info(f"Updating profile for user: {user_id}")
        user = await self.user_repository.get_by_id(user_id)
        if not user:
            logger.warning(f"User not found: {user_id}")
            raise ResourceNotFoundException("User not found")

        # Remove None values and fields that shouldn't be updated
        filtered_data = {k: v for k, v in update_data.items() if v is not None}

        # Don't allow updating sensitive fields
        restricted_fields = {
            "id",
            "password",
            "verification_code",
            "verification_code_expiry",
            "is_verified",
        }
        for field in restricted_fields:
            filtered_data.pop(field, None)

        if not filtered_data:
            # No valid updates provided
            user_schema = UserSchema.model_validate(user)
            return 200, user_schema

        updated_user = await self.user_repository.update_user(user_id, **filtered_data)
        user_schema = UserSchema.model_validate(updated_user)

        return 200, user_schema
