import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.base_repositories import BaseRepository
from app.modules.user_service.models.session_model import Session

logger = logging.getLogger(__name__)


class SessionRepository(BaseRepository[Session]):
    def __init__(self, session: AsyncSession):
        super().__init__(session, Session)

    async def create_session(self, session: Session) -> Session:
        """
        Create a new session in the database.
        :param session: Session object to be created.
        :return: The created Session object.
        """
        return await self.create(session)

    async def get_session_by_refresh_token(self, refresh_token: str) -> Session | None:
        """
        Retrieve a session by refresh token.
        :param refresh_token: The refresh token to search for.
        :return: Session object if found, otherwise None.
        """
        return await self.get_by_field("refresh_token", refresh_token)

    async def get_user_sessions(self, user_id: str) -> list[Session]:
        """
        Get all sessions for a specific user.
        :param user_id: The user ID to get sessions for.
        :return: List of Session objects.
        """
        stmt = (
            select(Session)
            .where(Session.user_id == user_id)
            .order_by(desc(Session.created_at))
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_active_sessions(self, user_id: str) -> list[Session]:
        """
        Get all active (non-expired) sessions for a user.
        :param user_id: The user ID to get sessions for.
        :return: List of active Session objects.
        """
        current_time = datetime.now(UTC)
        stmt = (
            select(Session)
            .where(and_(Session.user_id == user_id, Session.expires_at > current_time))
            .order_by(desc(Session.created_at))
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def delete_session(self, session_id: str) -> bool:
        """
        Delete a session by ID.

        :param session_id: The session ID to delete.
        :return: True if deleted, False if not found.
        """
        return await self.delete(session_id)

    async def delete_user_sessions(self, user_id: str) -> None:
        """
        Delete all sessions for a specific user.
        :param user_id: The user ID to delete sessions for.
        """
        sessions = await self.get_user_sessions(user_id)
        for session in sessions:
            await self.delete(session.id)

    async def delete_user_sessions_except_current(
        self, user_id: str, current_refresh_token: str
    ) -> None:
        """
        Delete all sessions for a user except the current one.
        :param user_id: The user ID to delete sessions for.
        :param current_refresh_token: The refresh token of the current session to keep.
        """
        sessions = await self.get_user_sessions(user_id)
        for session in sessions:
            if session.refresh_token != current_refresh_token:
                await self.delete(session.id)

    async def get_session_by_user_and_token(
        self, user_id: str, refresh_token: str
    ) -> Session | None:
        """
        Get a session by user ID and refresh token.
        :param user_id: The user ID.
        :param refresh_token: The refresh token.
        :return: Session object if found, otherwise None.
        """
        stmt = select(Session).where(
            and_(Session.user_id == user_id, Session.refresh_token == refresh_token)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def delete_expired_sessions(self, user_id: str) -> None:
        """
        Delete all expired sessions for a user.
        :param user_id: The user ID to clean up sessions for.
        """
        current_time = datetime.now(UTC)
        sessions = await self.get_user_sessions(user_id)
        for session in sessions:
            if session.expires_at <= current_time:
                await self.delete(session.id)

    async def enforce_session_limit(self, user_id: str, max_sessions: int = 4) -> None:
        """
        Enforce session limit by deleting oldest sessions if limit is exceeded.
        :param user_id: The user ID to enforce limit for.
        :param max_sessions: Maximum number of sessions allowed (default: 4).
        """
        sessions = await self.get_active_sessions(user_id)
        if len(sessions) >= max_sessions:
            # Delete oldest sessions to make room for new one
            sessions_to_delete = sessions[
                max_sessions - 1 :
            ]  # Keep max_sessions-1, delete rest
            for session in sessions_to_delete:
                await self.delete(session.id)

    async def update_session(self, session_id: str, **kwargs: Any) -> Session | None:
        """
        Update an existing session.
        :param session_id: The session ID to update.
        :param kwargs: Fields to update.
        :return: Updated Session object or None if not found.
        """
        return await self.update(session_id, **kwargs)

    async def is_session_valid(self, refresh_token: str) -> bool:
        """
        Check if a session is valid (exists and not expired).
        :param refresh_token: The refresh token to validate.
        :return: True if valid, False otherwise.
        """
        session = await self.get_session_by_refresh_token(refresh_token)
        if not session:
            return False

        current_time = datetime.now(UTC)
        return session.expires_at > current_time
