"""Tests for AuthService."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.exceptions.exceptions import (
    InvalidCredentialsException,
    ResourceAlreadyExistsException,
    ResourceNotFoundException,
    UnauthorizedAccessException,
    ValidationException,
)
from app.modules.user_service.models.user_model import User
from app.modules.user_service.schema.user_schema import (
    ForgotPasswordSchema,
    ResetPasswordSchema,
    UserLoginSchema,
    UserRegistrationSchema,
    VerifyUserSchema,
)
from app.modules.user_service.services.auth_service import AuthService


class TestAuthServiceRegister:
    """Tests for user registration."""

    @pytest.mark.asyncio
    async def test_register_new_user_success(
        self, auth_service: AuthService, mock_user_repository: MagicMock
    ) -> None:
        """Test successful registration of a new user."""
        # Arrange
        user_data = UserRegistrationSchema(
            name="New User",
            email="newuser@example.com",
            username="newuser",
            password="SecurePass123!",
        )

        mock_user_repository.get_by_email.return_value = None
        mock_user_repository.get_by_username.return_value = None
        mock_user_repository.create_user = AsyncMock(
            return_value=User(
                id="new-user-id",
                name=user_data.name,
                email=user_data.email,
                username=user_data.username,
                password="hashed_password",
                is_verified=False,
                verification_code="123456",
                verification_code_expiry=datetime.now(UTC) + timedelta(minutes=10),
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )

        # Act
        with patch(
            "app.modules.user_service.services.auth_service.resend_email_service.send_verification_email",
            new_callable=AsyncMock,
        ):
            status_code, response = await auth_service.register_user(user_data)

        # Assert
        assert status_code == 201
        assert response.user.email == user_data.email
        assert response.user.username == user_data.username
        mock_user_repository.create_user.assert_called_once()

    @pytest.mark.asyncio
    async def test_register_existing_verified_user_by_email(
        self,
        auth_service: AuthService,
        mock_user_repository: MagicMock,
        sample_user: User,
    ) -> None:
        """Test registration fails when email already exists with verified user."""
        # Arrange
        user_data = UserRegistrationSchema(
            name="Test User",
            email=sample_user.email,
            username="differentusername",
            password="SecurePass123!",
        )

        mock_user_repository.get_by_email.return_value = sample_user

        # Act & Assert
        with pytest.raises(ResourceAlreadyExistsException) as exc_info:
            await auth_service.register_user(user_data)

        assert "already exists with this email" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_register_existing_verified_user_by_username(
        self,
        auth_service: AuthService,
        mock_user_repository: MagicMock,
        sample_user: User,
    ) -> None:
        """Test registration fails when username already exists with verified user."""
        # Arrange
        user_data = UserRegistrationSchema(
            name="Test User",
            email="newemail@example.com",
            username=sample_user.username,
            password="SecurePass123!",
        )

        mock_user_repository.get_by_email.return_value = None
        mock_user_repository.get_by_username.return_value = sample_user

        # Act & Assert
        with pytest.raises(ResourceAlreadyExistsException) as exc_info:
            await auth_service.register_user(user_data)

        assert "already exists with username" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_register_update_unverified_user(
        self,
        auth_service: AuthService,
        mock_user_repository: MagicMock,
        unverified_user: User,
    ) -> None:
        """Test registration updates existing unverified user."""
        # Arrange
        user_data = UserRegistrationSchema(
            name="Updated Name",
            email=unverified_user.email,
            username="updatedusername",
            password="NewSecurePass123!",
        )

        mock_user_repository.get_by_email.return_value = unverified_user
        mock_user_repository.get_by_username.return_value = None
        mock_user_repository.update_user.return_value = unverified_user

        # Act
        with patch(
            "app.modules.user_service.services.auth_service.resend_email_service.send_verification_email",
            new_callable=AsyncMock,
        ):
            status_code, response = await auth_service.register_user(user_data)

        # Assert
        assert status_code == 200
        mock_user_repository.update_user.assert_called_once()


class TestAuthServiceLogin:
    """Tests for user login."""

    @pytest.mark.asyncio
    async def test_login_success(
        self,
        auth_service: AuthService,
        mock_user_repository: MagicMock,
        sample_user: User,
    ) -> None:
        """Test successful user login."""
        # Arrange
        login_data = UserLoginSchema(identifier="testuser", password="correct_password")

        mock_user_repository.get_by_identifier.return_value = sample_user

        with (
            patch(
                "app.modules.user_service.services.auth_service.PasswordUtils.check_password_hash",
                return_value=True,
            ),
            patch(
                "app.modules.user_service.services.auth_service.JWTUtils.create_access_token",
                return_value="access_token",
            ),
            patch(
                "app.modules.user_service.services.auth_service.JWTUtils.create_refresh_token",
                return_value="refresh_token",
            ),
        ):
            # Act
            (
                status_code,
                access_token,
                refresh_token,
                expires_in,
                user,
            ) = await auth_service.login_user(login_data, "Mozilla/5.0", "127.0.0.1")

        # Assert
        assert status_code == 200
        assert access_token == "access_token"
        assert refresh_token == "refresh_token"
        assert expires_in > 0
        assert user.email == sample_user.email

    @pytest.mark.asyncio
    async def test_login_user_not_found(
        self, auth_service: AuthService, mock_user_repository: MagicMock
    ) -> None:
        """Test login fails when user doesn't exist."""
        # Arrange
        login_data = UserLoginSchema(identifier="nonexistent", password="password")

        mock_user_repository.get_by_identifier.return_value = None

        # Act & Assert
        with pytest.raises(InvalidCredentialsException):
            await auth_service.login_user(login_data, "Mozilla/5.0", "127.0.0.1")

    @pytest.mark.asyncio
    async def test_login_user_not_verified(
        self,
        auth_service: AuthService,
        mock_user_repository: MagicMock,
        unverified_user: User,
    ) -> None:
        """Test login fails when user is not verified."""
        # Arrange
        login_data = UserLoginSchema(identifier="unverifieduser", password="password")

        mock_user_repository.get_by_identifier.return_value = unverified_user

        # Act & Assert
        with pytest.raises(UnauthorizedAccessException) as exc_info:
            await auth_service.login_user(login_data, "Mozilla/5.0", "127.0.0.1")

        assert "verify your email" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_login_invalid_password(
        self,
        auth_service: AuthService,
        mock_user_repository: MagicMock,
        sample_user: User,
    ) -> None:
        """Test login fails with incorrect password."""
        # Arrange
        login_data = UserLoginSchema(identifier="testuser", password="wrong_password")

        mock_user_repository.get_by_identifier.return_value = sample_user

        with patch(
            "app.modules.user_service.utils.auth_utils.PasswordUtils.check_password_hash",
            return_value=False,
        ):
            # Act & Assert
            with pytest.raises(InvalidCredentialsException):
                await auth_service.login_user(login_data, "Mozilla/5.0", "127.0.0.1")


class TestAuthServiceVerification:
    """Tests for email verification."""

    @pytest.mark.asyncio
    async def test_verify_user_success(
        self,
        auth_service: AuthService,
        mock_user_repository: MagicMock,
        unverified_user: User,
    ) -> None:
        """Test successful user verification."""
        # Arrange
        verify_data = VerifyUserSchema(
            identifier=unverified_user.email, verification_code="123456"
        )

        mock_user_repository.get_by_identifier.return_value = unverified_user
        mock_user_repository.update_user.return_value = unverified_user

        # Act
        with patch(
            "app.modules.user_service.services.auth_service.resend_email_service.send_welcome_email",
            new_callable=AsyncMock,
        ):
            status_code, response = await auth_service.verify_user(verify_data)

        # Assert
        assert status_code == 200
        mock_user_repository.update_user.assert_called_once()

    @pytest.mark.asyncio
    async def test_verify_user_not_found(
        self, auth_service: AuthService, mock_user_repository: MagicMock
    ) -> None:
        """Test verification fails when user doesn't exist."""
        # Arrange
        verify_data = VerifyUserSchema(
            identifier="nonexistent@example.com", verification_code="123456"
        )

        mock_user_repository.get_by_identifier.return_value = None

        # Act & Assert
        with pytest.raises(ResourceNotFoundException):
            await auth_service.verify_user(verify_data)

    @pytest.mark.asyncio
    async def test_verify_user_invalid_code(
        self,
        auth_service: AuthService,
        mock_user_repository: MagicMock,
        unverified_user: User,
    ) -> None:
        """Test verification fails with invalid code."""
        # Arrange
        verify_data = VerifyUserSchema(
            identifier=unverified_user.email, verification_code="wrong_code"
        )

        mock_user_repository.get_by_identifier.return_value = unverified_user

        # Act & Assert
        with pytest.raises(InvalidCredentialsException) as exc_info:
            await auth_service.verify_user(verify_data)

        assert "invalid" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_verify_user_expired_code(
        self,
        auth_service: AuthService,
        mock_user_repository: MagicMock,
        unverified_user: User,
    ) -> None:
        """Test verification fails with expired code."""
        # Arrange
        unverified_user.verification_code_expiry = datetime.now(UTC) - timedelta(
            minutes=1
        )
        verify_data = VerifyUserSchema(
            identifier=unverified_user.email, verification_code="123456"
        )

        mock_user_repository.get_by_identifier.return_value = unverified_user

        # Act & Assert
        with pytest.raises(ValidationException) as exc_info:
            await auth_service.verify_user(verify_data)

        assert "expired" in str(exc_info.value).lower()


class TestAuthServicePasswordReset:
    """Tests for password reset functionality."""

    @pytest.mark.asyncio
    async def test_forgot_password_success(
        self,
        auth_service: AuthService,
        mock_user_repository: MagicMock,
        sample_user: User,
    ) -> None:
        """Test successful forgot password request."""
        # Arrange
        forgot_data = ForgotPasswordSchema(identifier=sample_user.email)

        mock_user_repository.get_by_identifier.return_value = sample_user
        mock_user_repository.update_user.return_value = sample_user

        # Act
        with patch(
            "app.modules.user_service.services.auth_service.resend_email_service.send_password_reset_email",
            new_callable=AsyncMock,
        ):
            status_code, response = await auth_service.forgot_password(forgot_data)

        # Assert
        assert status_code == 200
        mock_user_repository.update_user.assert_called_once()

    @pytest.mark.asyncio
    async def test_reset_password_success(
        self,
        auth_service: AuthService,
        mock_user_repository: MagicMock,
        sample_user: User,
    ) -> None:
        """Test successful password reset."""
        # Arrange
        sample_user.verification_code = "123456"
        sample_user.verification_code_expiry = datetime.now(UTC) + timedelta(minutes=10)

        reset_data = ResetPasswordSchema(
            identifier=sample_user.email,
            verification_code="123456",
            new_password="NewSecurePass123!",
        )

        mock_user_repository.get_by_identifier.return_value = sample_user
        mock_user_repository.update_user.return_value = sample_user

        # Act
        status_code, response = await auth_service.reset_password(reset_data)

        # Assert
        assert status_code == 200
        mock_user_repository.update_user.assert_called_once()

    @pytest.mark.asyncio
    async def test_reset_password_invalid_code(
        self,
        auth_service: AuthService,
        mock_user_repository: MagicMock,
        sample_user: User,
    ) -> None:
        """Test password reset fails with invalid code."""
        # Arrange
        sample_user.verification_code = "123456"
        sample_user.verification_code_expiry = datetime.now(UTC) + timedelta(minutes=10)

        reset_data = ResetPasswordSchema(
            identifier=sample_user.email,
            verification_code="wrong_code",
            new_password="NewSecurePass123!",
        )

        mock_user_repository.get_by_identifier.return_value = sample_user

        # Act & Assert
        with pytest.raises(InvalidCredentialsException):
            await auth_service.reset_password(reset_data)
