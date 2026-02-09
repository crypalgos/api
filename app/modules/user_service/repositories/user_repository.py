import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.base_repositories import BaseRepository
from app.modules.user_service.models.user_model import User

logger = logging.getLogger(__name__)


class UserRepository(BaseRepository[User]):
    def __init__(self, session: AsyncSession):
        super().__init__(session, User)

    async def get_by_email(self, email: str) -> User | None:
        """
        Retrieve a user by their email address.

        :param email: The email address of the user to retrieve.
        :return: User object if found, otherwise None.
        """
        return await self.get_by_field("email", email)

    async def get_by_username(self, username: str) -> User | None:
        """
        Retrieve a user by their username.

        :param username: The username of the user to retrieve.
        :return: User object if found, otherwise None.
        """
        return await self.get_by_field("username", username)

    async def get_by_identifier(self, identifier: str) -> User | None:
        """
        Retrieve a user by their unique identifier username /email.

        :return: User object if found, otherwise None.
        """
        select_stmt = select(User).where(
            (User.email == identifier) | (User.username == identifier)
        )
        result = await self.session.execute(select_stmt)
        user = result.scalars().first()
        return user if user else None

    async def create_user(self, user: User) -> User:
        """
        Create a new user in the database.

        :param user: User object to be created.
        :return: The created User object.
        """
        return await self.create(user)

    async def update_user(self, id: str, **kwargs) -> User:
        """
        Update an existing user in the database.

        :param user: User object with updated information.
        :return: The updated User object.
        """
        return await self.update(id, **kwargs)

    async def delete_user(self, id: str) -> bool:
        """
        Delete a user from the database.

        :param id: The ID of the user to delete.
        """
        await self.delete(id)
        return True

    async def get_paginated_users(
        self, _offset: int = 0, _limit: int = 10, _query: str = ""
    ) -> dict[str, int | list[Any]]:
        """
        Retrieve paginated users with optional search query.

        :param _offset: The starting point for pagination.
        :param _limit: The number of users to return.
        :param _query: Optional search query to filter users by name or email.
        :return: A dictionary containing paginated user data.
        """
        # This method should be implemented in base repository
        return {"total": 0, "items": []}
