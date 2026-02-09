import logging

from app.exceptions.exceptions import ResourceNotFoundException

from ..repositories.session_repository import SessionRepository
from ..repositories.user_repository import UserRepository
from ..schema.user_schema import (
    GenericMessageSchema,
    SessionSchema,
    UserSessionsResponseSchema,
)

logger = logging.getLogger(__name__)


class SessionService:
    def __init__(
        self, session_repository: SessionRepository, user_repository: UserRepository
    ):
        self.session_repository = session_repository
        self.user_repository = user_repository

    async def get_user_sessions(
        self, user_id: str
    ) -> tuple[int, UserSessionsResponseSchema]:
        """Get all active sessions for a user"""
        logger.info(f"Fetching sessions for user: {user_id}")
        # Verify user exists
        user = await self.user_repository.get_by_id(user_id)
        if not user:
            logger.warning(f"User not found: {user_id}")
            raise ResourceNotFoundException("User not found")

        # Get active sessions
        sessions = await self.session_repository.get_active_sessions(user_id)

        # Convert to schema
        session_schemas = []
        for session in sessions:
            session_schema = SessionSchema.model_validate(session)
            session_schemas.append(session_schema)

        response = UserSessionsResponseSchema(
            sessions=session_schemas, total_sessions=len(session_schemas)
        )

        return 200, response

    async def delete_session(
        self, user_id: str, session_id: str, current_refresh_token: str
    ) -> tuple[int, GenericMessageSchema]:
        """Delete a specific session (cannot delete current session)"""
        logger.info(f"Deleting session {session_id} for user: {user_id}")
        # Verify user exists
        user = await self.user_repository.get_by_id(user_id)
        if not user:
            logger.warning(f"User not found: {user_id}")
            raise ResourceNotFoundException("User not found")

        # Get session and verify it belongs to the user
        session = await self.session_repository.get_by_id(session_id)
        if not session:
            raise ResourceNotFoundException("Session not found")

        if session.user_id != user_id:
            raise ResourceNotFoundException("Session not found")

        # Prevent deleting current session
        if session.refresh_token == current_refresh_token:
            from app.exceptions.exceptions import InvalidOperationException

            raise InvalidOperationException(
                "Cannot delete your current session. Use logout instead."
            )

        # Delete session
        await self.session_repository.delete_session(session_id)

        return 200, GenericMessageSchema(message="Session deleted successfully")

    async def delete_all_sessions(
        self, user_id: str, current_refresh_token: str
    ) -> tuple[int, GenericMessageSchema]:
        """Delete all sessions for a user except the current one (logout from all other devices)"""
        logger.info(f"Deleting all other sessions for user: {user_id}")
        # Verify user exists
        user = await self.user_repository.get_by_id(user_id)
        if not user:
            logger.warning(f"User not found: {user_id}")
            raise ResourceNotFoundException("User not found")

        # Delete all user sessions except current one
        await self.session_repository.delete_user_sessions_except_current(
            user_id, current_refresh_token
        )

        return 200, GenericMessageSchema(
            message="All other sessions deleted successfully"
        )
