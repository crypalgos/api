"""Tests for UserRepository."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.user_service.models.user_model import User
from app.modules.user_service.repositories.user_repository import UserRepository


class TestUserRepositoryGetByEmail:
    """Tests for getting user by email."""

    @pytest.mark.asyncio
    async def test_get_by_email_found(
        self, mock_db_session: AsyncSession, sample_user: User
    ) -> None:
        """Test getting user by email when user exists."""
        # Arrange
        repository = UserRepository(mock_db_session)
        repository.get_by_field = AsyncMock(return_value=sample_user)

        # Act
        result = await repository.get_by_email(sample_user.email)

        # Assert
        assert result == sample_user
        repository.get_by_field.assert_called_once_with("email", sample_user.email)

    @pytest.mark.asyncio
    async def test_get_by_email_not_found(self, mock_db_session: AsyncSession) -> None:
        """Test getting user by email when user doesn't exist."""
        # Arrange
        repository = UserRepository(mock_db_session)
        repository.get_by_field = AsyncMock(return_value=None)

        # Act
        result = await repository.get_by_email("nonexistent@example.com")

        # Assert
        assert result is None


class TestUserRepositoryGetByUsername:
    """Tests for getting user by username."""

    @pytest.mark.asyncio
    async def test_get_by_username_found(
        self, mock_db_session: AsyncSession, sample_user: User
    ) -> None:
        """Test getting user by username when user exists."""
        # Arrange
        repository = UserRepository(mock_db_session)
        repository.get_by_field = AsyncMock(return_value=sample_user)

        # Act
        result = await repository.get_by_username(sample_user.username)

        # Assert
        assert result == sample_user
        repository.get_by_field.assert_called_once_with(
            "username", sample_user.username
        )

    @pytest.mark.asyncio
    async def test_get_by_username_not_found(
        self, mock_db_session: AsyncSession
    ) -> None:
        """Test getting user by username when user doesn't exist."""
        # Arrange
        repository = UserRepository(mock_db_session)
        repository.get_by_field = AsyncMock(return_value=None)

        # Act
        result = await repository.get_by_username("nonexistent")

        # Assert
        assert result is None


class TestUserRepositoryGetByIdentifier:
    """Tests for getting user by identifier (email or username)."""

    @pytest.mark.asyncio
    async def test_get_by_identifier_email(
        self, mock_db_session: AsyncSession, sample_user: User
    ) -> None:
        """Test getting user by email identifier."""
        # Arrange
        repository = UserRepository(mock_db_session)

        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.first.return_value = sample_user
        mock_result.scalars.return_value = mock_scalars
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        # Act
        result = await repository.get_by_identifier(sample_user.email)

        # Assert
        assert result == sample_user
        mock_db_session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_by_identifier_username(
        self, mock_db_session: AsyncSession, sample_user: User
    ) -> None:
        """Test getting user by username identifier."""
        # Arrange
        repository = UserRepository(mock_db_session)

        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.first.return_value = sample_user
        mock_result.scalars.return_value = mock_scalars
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        # Act
        result = await repository.get_by_identifier(sample_user.username)

        # Assert
        assert result == sample_user

    @pytest.mark.asyncio
    async def test_get_by_identifier_not_found(
        self, mock_db_session: AsyncSession
    ) -> None:
        """Test getting user by identifier when user doesn't exist."""
        # Arrange
        repository = UserRepository(mock_db_session)

        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.first.return_value = None
        mock_result.scalars.return_value = mock_scalars
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        # Act
        result = await repository.get_by_identifier("nonexistent")

        # Assert
        assert result is None


class TestUserRepositoryCRUD:
    """Tests for CRUD operations."""

    @pytest.mark.asyncio
    async def test_create_user(
        self, mock_db_session: AsyncSession, sample_user: User
    ) -> None:
        """Test creating a new user."""
        # Arrange
        repository = UserRepository(mock_db_session)
        repository.create = AsyncMock(return_value=sample_user)

        # Act
        result = await repository.create_user(sample_user)

        # Assert
        assert result == sample_user
        repository.create.assert_called_once_with(sample_user)

    @pytest.mark.asyncio
    async def test_update_user(
        self, mock_db_session: AsyncSession, sample_user: User
    ) -> None:
        """Test updating a user."""
        # Arrange
        repository = UserRepository(mock_db_session)
        updated_data = {"name": "Updated Name"}
        repository.update = AsyncMock(return_value=sample_user)

        # Act
        result = await repository.update_user(sample_user.id, **updated_data)

        # Assert
        assert result == sample_user
        repository.update.assert_called_once_with(sample_user.id, **updated_data)

    @pytest.mark.asyncio
    async def test_delete_user(
        self, mock_db_session: AsyncSession, sample_user: User
    ) -> None:
        """Test deleting a user."""
        # Arrange
        repository = UserRepository(mock_db_session)
        repository.delete = AsyncMock()

        # Act
        await repository.delete_user(sample_user.id)

        # Assert
        repository.delete.assert_called_once_with(sample_user.id)
