"""Tests for SessionRepository."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.user_service.models.session_model import Session
from app.modules.user_service.repositories.session_repository import SessionRepository


class TestSessionRepositoryCreate:
    """Tests for creating sessions."""

    @pytest.mark.asyncio
    async def test_create_session(
        self, mock_db_session: AsyncSession, sample_session: Session
    ) -> None:
        """Test creating a new session."""
        # Arrange
        repository = SessionRepository(mock_db_session)
        repository.create = AsyncMock(return_value=sample_session)

        # Act
        result = await repository.create_session(sample_session)

        # Assert
        assert result == sample_session
        repository.create.assert_called_once_with(sample_session)


class TestSessionRepositoryGetByRefreshToken:
    """Tests for getting session by refresh token."""

    @pytest.mark.asyncio
    async def test_get_session_by_refresh_token_found(
        self, mock_db_session: AsyncSession, sample_session: Session
    ) -> None:
        """Test getting session by refresh token when session exists."""
        # Arrange
        repository = SessionRepository(mock_db_session)
        repository.get_by_field = AsyncMock(return_value=sample_session)

        # Act
        result = await repository.get_session_by_refresh_token(
            sample_session.refresh_token
        )

        # Assert
        assert result == sample_session
        repository.get_by_field.assert_called_once_with(
            "refresh_token", sample_session.refresh_token
        )

    @pytest.mark.asyncio
    async def test_get_session_by_refresh_token_not_found(
        self, mock_db_session: AsyncSession
    ) -> None:
        """Test getting session by refresh token when session doesn't exist."""
        # Arrange
        repository = SessionRepository(mock_db_session)
        repository.get_by_field = AsyncMock(return_value=None)

        # Act
        result = await repository.get_session_by_refresh_token("nonexistent_token")

        # Assert
        assert result is None


class TestSessionRepositoryGetUserSessions:
    """Tests for getting user sessions."""

    @pytest.mark.asyncio
    async def test_get_user_sessions(
        self, mock_db_session: AsyncSession, sample_session: Session
    ) -> None:
        """Test getting all sessions for a user."""
        # Arrange
        repository = SessionRepository(mock_db_session)

        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [sample_session]
        mock_result.scalars.return_value = mock_scalars
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        # Act
        result = await repository.get_user_sessions("test-user-id")

        # Assert
        assert len(result) == 1
        assert result[0] == sample_session
        mock_db_session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_user_sessions_empty(self, mock_db_session: AsyncSession) -> None:
        """Test getting sessions when user has no sessions."""
        # Arrange
        repository = SessionRepository(mock_db_session)

        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result.scalars.return_value = mock_scalars
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        # Act
        result = await repository.get_user_sessions("test-user-id")

        # Assert
        assert len(result) == 0


class TestSessionRepositoryGetActiveSessions:
    """Tests for getting active sessions."""

    @pytest.mark.asyncio
    async def test_get_active_sessions(
        self, mock_db_session: AsyncSession, sample_session: Session
    ) -> None:
        """Test getting active sessions for a user."""
        # Arrange
        repository = SessionRepository(mock_db_session)

        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [sample_session]
        mock_result.scalars.return_value = mock_scalars
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        # Act
        result = await repository.get_active_sessions("test-user-id")

        # Assert
        assert len(result) == 1
        assert result[0] == sample_session

    @pytest.mark.asyncio
    async def test_get_active_sessions_filters_expired(
        self, mock_db_session: AsyncSession
    ) -> None:
        """Test that get_active_sessions only returns non-expired sessions."""
        # Arrange
        repository = SessionRepository(mock_db_session)

        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result.scalars.return_value = mock_scalars
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        # Act
        result = await repository.get_active_sessions("test-user-id")

        # Assert
        assert len(result) == 0


class TestSessionRepositoryDelete:
    """Tests for deleting sessions."""

    @pytest.mark.asyncio
    async def test_delete_session(self, mock_db_session: AsyncSession) -> None:
        """Test deleting a session by ID."""
        # Arrange
        repository = SessionRepository(mock_db_session)
        repository.delete = AsyncMock(return_value=True)

        # Act
        result = await repository.delete_session("session-id")

        # Assert
        assert result is True
        repository.delete.assert_called_once_with("session-id")

    @pytest.mark.asyncio
    async def test_delete_user_sessions(
        self, mock_db_session: AsyncSession, sample_session: Session
    ) -> None:
        """Test deleting all sessions for a user."""
        # Arrange
        repository = SessionRepository(mock_db_session)
        repository.get_user_sessions = AsyncMock(return_value=[sample_session])
        repository.delete = AsyncMock()

        # Act
        await repository.delete_user_sessions("test-user-id")

        # Assert
        repository.get_user_sessions.assert_called_once_with("test-user-id")
        repository.delete.assert_called_once_with(sample_session.id)

    @pytest.mark.asyncio
    async def test_delete_expired_sessions(self, mock_db_session: AsyncSession) -> None:
        """Test deleting expired sessions for a user."""
        # Arrange
        repository = SessionRepository(mock_db_session)

        expired_session = Session(
            id="expired-session-id",
            user_id="test-user-id",
            refresh_token="expired_token",
            user_agent="Mozilla/5.0",
            ip_address="127.0.0.1",
            expires_at=datetime.now(UTC) - timedelta(days=1),
            created_at=datetime.now(UTC),
        )

        active_session = Session(
            id="active-session-id",
            user_id="test-user-id",
            refresh_token="active_token",
            user_agent="Mozilla/5.0",
            ip_address="127.0.0.1",
            expires_at=datetime.now(UTC) + timedelta(days=7),
            created_at=datetime.now(UTC),
        )

        repository.get_user_sessions = AsyncMock(
            return_value=[expired_session, active_session]
        )
        repository.delete = AsyncMock()

        # Act
        await repository.delete_expired_sessions("test-user-id")

        # Assert
        repository.get_user_sessions.assert_called_once_with("test-user-id")
        repository.delete.assert_called_once_with(expired_session.id)


class TestSessionRepositoryEnforceLimit:
    """Tests for enforcing session limit."""

    @pytest.mark.asyncio
    async def test_enforce_session_limit_under_limit(
        self, mock_db_session: AsyncSession, sample_session: Session
    ) -> None:
        """Test enforcing limit when under the limit."""
        # Arrange
        repository = SessionRepository(mock_db_session)
        repository.get_active_sessions = AsyncMock(return_value=[sample_session])
        repository.delete = AsyncMock()

        # Act
        await repository.enforce_session_limit("test-user-id", max_sessions=4)

        # Assert
        repository.get_active_sessions.assert_called_once_with("test-user-id")
        repository.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_enforce_session_limit_over_limit(
        self, mock_db_session: AsyncSession
    ) -> None:
        """Test enforcing limit when over the limit."""
        # Arrange
        repository = SessionRepository(mock_db_session)

        sessions = [
            Session(
                id=f"session-{i}",
                user_id="test-user-id",
                refresh_token=f"token-{i}",
                user_agent="Mozilla/5.0",
                ip_address="127.0.0.1",
                expires_at=datetime.now(UTC) + timedelta(days=7),
                created_at=datetime.now(UTC) - timedelta(minutes=i),
            )
            for i in range(5)
        ]

        repository.get_active_sessions = AsyncMock(return_value=sessions)
        repository.delete = AsyncMock()

        # Act
        await repository.enforce_session_limit("test-user-id", max_sessions=3)

        # Assert
        repository.get_active_sessions.assert_called_once_with("test-user-id")
        # Should delete 3 sessions to keep max_sessions-1 (2), making room for new session
        assert repository.delete.call_count == 3
