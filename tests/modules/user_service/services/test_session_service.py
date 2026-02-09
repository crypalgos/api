"""Tests for SessionService."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.exceptions.exceptions import ResourceNotFoundException
from app.modules.user_service.models.session_model import Session
from app.modules.user_service.models.user_model import User
from app.modules.user_service.services.session_service import SessionService


class TestSessionServiceGetUserSessions:
    """Tests for getting user sessions."""

    @pytest.mark.asyncio
    async def test_get_user_sessions_success(
        self,
        session_service: SessionService,
        mock_user_repository: MagicMock,
        mock_session_repository: MagicMock,
        sample_user: User,
        sample_session: Session,
    ) -> None:
        """Test successfully getting user sessions."""
        # Arrange
        mock_user_repository.get_by_id.return_value = sample_user
        mock_session_repository.get_active_sessions = AsyncMock(
            return_value=[sample_session]
        )

        # Act
        status_code, response = await session_service.get_user_sessions(sample_user.id)

        # Assert
        assert status_code == 200
        assert response.total_sessions == 1
        assert len(response.sessions) == 1
        assert response.sessions[0].id == sample_session.id

    @pytest.mark.asyncio
    async def test_get_user_sessions_user_not_found(
        self, session_service: SessionService, mock_user_repository: MagicMock
    ) -> None:
        """Test getting sessions fails when user doesn't exist."""
        # Arrange
        mock_user_repository.get_by_id.return_value = None

        # Act & Assert
        with pytest.raises(ResourceNotFoundException) as exc_info:
            await session_service.get_user_sessions("nonexistent-user-id")

        assert "User not found" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_get_user_sessions_empty_list(
        self,
        session_service: SessionService,
        mock_user_repository: MagicMock,
        mock_session_repository: MagicMock,
        sample_user: User,
    ) -> None:
        """Test getting sessions returns empty list when no sessions exist."""
        # Arrange
        mock_user_repository.get_by_id.return_value = sample_user
        mock_session_repository.get_active_sessions.return_value = []

        # Act
        status_code, response = await session_service.get_user_sessions(sample_user.id)

        # Assert
        assert status_code == 200
        assert response.total_sessions == 0
        assert len(response.sessions) == 0


class TestSessionServiceDeleteSession:
    """Tests for deleting a specific session."""

    @pytest.mark.asyncio
    async def test_delete_session_success(
        self,
        session_service: SessionService,
        mock_user_repository: MagicMock,
        mock_session_repository: MagicMock,
        sample_user: User,
        sample_session: Session,
    ) -> None:
        """Test successfully deleting a session."""
        # Arrange
        mock_user_repository.get_by_id.return_value = sample_user
        mock_session_repository.get_by_id.return_value = sample_session
        mock_session_repository.delete_session.return_value = True

        # Act
        status_code, response = await session_service.delete_session(
            sample_user.id, sample_session.id, "dummy_refresh_token"
        )

        # Assert
        assert status_code == 200
        assert "deleted successfully" in response.message
        mock_session_repository.delete_session.assert_called_once_with(
            sample_session.id
        )

    @pytest.mark.asyncio
    async def test_delete_session_user_not_found(
        self, session_service: SessionService, mock_user_repository: MagicMock
    ) -> None:
        """Test deleting session fails when user doesn't exist."""
        # Arrange
        mock_user_repository.get_by_id.return_value = None

        # Act & Assert
        with pytest.raises(ResourceNotFoundException) as exc_info:
            await session_service.delete_session("nonexistent-user-id", "session-id", "dummy_refresh_token")

        assert "User not found" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_delete_session_not_found(
        self,
        session_service: SessionService,
        mock_user_repository: MagicMock,
        mock_session_repository: MagicMock,
        sample_user: User,
    ) -> None:
        """Test deleting session fails when session doesn't exist."""
        # Arrange
        mock_user_repository.get_by_id.return_value = sample_user
        mock_session_repository.get_by_id.return_value = None

        # Act & Assert
        with pytest.raises(ResourceNotFoundException) as exc_info:
            await session_service.delete_session(sample_user.id, "nonexistent-session", "dummy_refresh_token")

        assert "Session not found" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_delete_session_wrong_user(
        self,
        session_service: SessionService,
        mock_user_repository: MagicMock,
        mock_session_repository: MagicMock,
        sample_user: User,
        sample_session: Session,
    ) -> None:
        """Test deleting session fails when session belongs to different user."""
        # Arrange
        mock_user_repository.get_by_id.return_value = sample_user
        sample_session.user_id = "different-user-id"
        mock_session_repository.get_by_id.return_value = sample_session

        # Act & Assert
        with pytest.raises(ResourceNotFoundException) as exc_info:
            await session_service.delete_session(sample_user.id, sample_session.id, "dummy_refresh_token")

        assert "Session not found" in str(exc_info.value)


class TestSessionServiceDeleteAllSessions:
    """Tests for deleting all user sessions."""

    @pytest.mark.asyncio
    async def test_delete_all_sessions_success(
        self,
        session_service: SessionService,
        mock_user_repository: MagicMock,
        mock_session_repository: MagicMock,
        sample_user: User,
    ) -> None:
        """Test successfully deleting all sessions."""
        # Arrange
        mock_user_repository.get_by_id.return_value = sample_user
        mock_session_repository.delete_user_sessions_except_current = AsyncMock()

        # Act
        status_code, response = await session_service.delete_all_sessions(
            sample_user.id, "dummy_refresh_token"
        )

        # Assert
        assert status_code == 200
        assert "All other sessions deleted successfully" in response.message
        mock_session_repository.delete_user_sessions_except_current.assert_called_once_with(
            sample_user.id, "dummy_refresh_token"
        )

    @pytest.mark.asyncio
    async def test_delete_all_sessions_user_not_found(
        self, session_service: SessionService, mock_user_repository: MagicMock
    ) -> None:
        """Test deleting all sessions fails when user doesn't exist."""
        # Arrange
        mock_user_repository.get_by_id.return_value = None

        # Act & Assert
        with pytest.raises(ResourceNotFoundException) as exc_info:
            await session_service.delete_all_sessions("nonexistent-user-id", "dummy_refresh_token")

        assert "User not found" in str(exc_info.value)



