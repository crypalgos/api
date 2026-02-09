"""Tests for UserService."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.exceptions.exceptions import ResourceNotFoundException
from app.modules.user_service.models.user_model import User
from app.modules.user_service.services.user_service import UserService


class TestUserServiceGetProfile:
    """Tests for getting user profile."""

    @pytest.mark.asyncio
    async def test_get_user_profile_success(
        self,
        user_service: UserService,
        mock_user_repository: MagicMock,
        sample_user: User,
    ) -> None:
        """Test successfully getting user profile."""
        # Arrange
        mock_user_repository.get_by_id.return_value = sample_user

        # Act
        status_code, response = await user_service.get_user_profile(sample_user.id)

        # Assert
        assert status_code == 200
        assert response.id == sample_user.id
        assert response.email == sample_user.email
        assert response.username == sample_user.username

    @pytest.mark.asyncio
    async def test_get_user_profile_not_found(
        self, user_service: UserService, mock_user_repository: MagicMock
    ) -> None:
        """Test getting profile fails when user doesn't exist."""
        # Arrange
        mock_user_repository.get_by_id.return_value = None

        # Act & Assert
        with pytest.raises(ResourceNotFoundException) as exc_info:
            await user_service.get_user_profile("nonexistent-user-id")

        assert "User not found" in str(exc_info.value)


class TestUserServiceDeleteAccount:
    """Tests for deleting user account."""

    @pytest.mark.asyncio
    async def test_delete_user_account_success(
        self,
        user_service: UserService,
        mock_user_repository: MagicMock,
        sample_user: User,
    ) -> None:
        """Test successfully deleting user account."""
        # Arrange
        mock_user_repository.get_by_id.return_value = sample_user
        mock_user_repository.delete_user = AsyncMock()

        # Act
        status_code, response = await user_service.delete_user_account(sample_user.id)

        # Assert
        assert status_code == 200
        assert "deleted successfully" in response.message
        mock_user_repository.delete_user.assert_called_once_with(sample_user.id)

    @pytest.mark.asyncio
    async def test_delete_user_account_not_found(
        self, user_service: UserService, mock_user_repository: MagicMock
    ) -> None:
        """Test deleting account fails when user doesn't exist."""
        # Arrange
        mock_user_repository.get_by_id.return_value = None

        # Act & Assert
        with pytest.raises(ResourceNotFoundException) as exc_info:
            await user_service.delete_user_account("nonexistent-user-id")

        assert "User not found" in str(exc_info.value)


class TestUserServiceUpdateProfile:
    """Tests for updating user profile."""

    @pytest.mark.asyncio
    async def test_update_user_profile_success(
        self,
        user_service: UserService,
        mock_user_repository: MagicMock,
        sample_user: User,
    ) -> None:
        """Test successfully updating user profile."""
        # Arrange
        update_data = {"name": "Updated Name", "username": "updatedusername"}

        mock_user_repository.get_by_id.return_value = sample_user
        updated_user = User(
            id=sample_user.id,
            name="Updated Name",
            email=sample_user.email,
            username="updatedusername",
            password=sample_user.password,
            is_verified=sample_user.is_verified,
            verification_code=sample_user.verification_code,
            verification_code_expiry=sample_user.verification_code_expiry,
            created_at=sample_user.created_at,
            updated_at=sample_user.updated_at,
        )
        mock_user_repository.update_user.return_value = updated_user

        # Act
        status_code, response = await user_service.update_user_profile(
            sample_user.id, **update_data
        )

        # Assert
        assert status_code == 200
        assert response.name == "Updated Name"
        assert response.username == "updatedusername"
        mock_user_repository.update_user.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_user_profile_user_not_found(
        self, user_service: UserService, mock_user_repository: MagicMock
    ) -> None:
        """Test updating profile fails when user doesn't exist."""
        # Arrange
        mock_user_repository.get_by_id.return_value = None

        # Act & Assert
        with pytest.raises(ResourceNotFoundException) as exc_info:
            await user_service.update_user_profile(
                "nonexistent-user-id", name="New Name"
            )

        assert "User not found" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_update_user_profile_no_changes(
        self,
        user_service: UserService,
        mock_user_repository: MagicMock,
        sample_user: User,
    ) -> None:
        """Test updating profile with no valid changes returns current user."""
        # Arrange
        mock_user_repository.get_by_id.return_value = sample_user

        # Act
        status_code, response = await user_service.update_user_profile(sample_user.id)

        # Assert
        assert status_code == 200
        assert response.id == sample_user.id
        # No changes were made, so the service returns the existing user

    @pytest.mark.asyncio
    async def test_update_user_profile_filters_restricted_fields(
        self,
        user_service: UserService,
        mock_user_repository: MagicMock,
        sample_user: User,
    ) -> None:
        """Test updating profile filters out restricted fields."""
        # Arrange
        update_data = {
            "name": "Updated Name",
            "password": "should_be_filtered",
            "is_verified": True,
            "verification_code": "123456",
        }

        mock_user_repository.get_by_id.return_value = sample_user
        updated_user = User(
            id=sample_user.id,
            name="Updated Name",
            email=sample_user.email,
            username=sample_user.username,
            password=sample_user.password,
            is_verified=sample_user.is_verified,
            verification_code=sample_user.verification_code,
            verification_code_expiry=sample_user.verification_code_expiry,
            created_at=sample_user.created_at,
            updated_at=sample_user.updated_at,
        )
        mock_user_repository.update_user.return_value = updated_user

        # Act
        status_code, response = await user_service.update_user_profile(
            sample_user.id, **update_data
        )

        # Assert
        assert status_code == 200
        # Verify update_user was called without restricted fields
        call_args = mock_user_repository.update_user.call_args
        assert "password" not in call_args[1]
        assert "is_verified" not in call_args[1]
        assert "verification_code" not in call_args[1]

    @pytest.mark.asyncio
    async def test_update_user_profile_filters_none_values(
        self,
        user_service: UserService,
        mock_user_repository: MagicMock,
        sample_user: User,
    ) -> None:
        """Test updating profile filters out None values."""
        # Arrange
        update_data = {"name": "Updated Name", "username": None, "email": None}

        mock_user_repository.get_by_id.return_value = sample_user
        updated_user = User(
            id=sample_user.id,
            name="Updated Name",
            email=sample_user.email,
            username=sample_user.username,
            password=sample_user.password,
            is_verified=sample_user.is_verified,
            verification_code=sample_user.verification_code,
            verification_code_expiry=sample_user.verification_code_expiry,
            created_at=sample_user.created_at,
            updated_at=sample_user.updated_at,
        )
        mock_user_repository.update_user.return_value = updated_user

        # Act
        status_code, response = await user_service.update_user_profile(
            sample_user.id, **update_data
        )

        # Assert
        assert status_code == 200
        # Verify update_user was called only with non-None values
        call_args = mock_user_repository.update_user.call_args
        assert "name" in call_args[1]
        assert "username" not in call_args[1]
        assert "email" not in call_args[1]
