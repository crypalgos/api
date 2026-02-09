"""Tests for auth routes."""

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.main import app
from app.modules.user_service.schema.user_schema import (
    UserRegistrationResponseSchema,
    UserSchema,
)


@pytest.fixture
def client() -> TestClient:
    """Create a test client."""
    return TestClient(app)


class TestAuthRegister:
    """Tests for user registration endpoint."""

    def test_register_success(
        self, client: TestClient, override_get_db, override_auth_service: MagicMock
    ) -> None:
        """Test successful user registration."""
        from datetime import UTC, datetime

        user_schema = UserSchema(
            id="test-id",
            name="Test User",
            email="test@example.com",
            username="testuser",
            is_verified=False,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        override_auth_service.register_user.return_value = (
            201,
            UserRegistrationResponseSchema(user=user_schema),
        )

        response = client.post(
            "/api/v1/auth/register",
            json={
                "name": "Test User",
                "email": "test@example.com",
                "username": "testuser",
                "password": "SecurePass123!",
            },
        )

        assert response.status_code == status.HTTP_201_CREATED

    def test_register_validation_error(
        self, client: TestClient, override_get_db, override_auth_service: MagicMock
    ) -> None:
        """Test registration with invalid data."""
        response = client.post(
            "/api/v1/auth/register",
            json={
                "name": "Test User",
                "email": "invalid-email",
                "username": "tu",
                "password": "weak",
            },
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


class TestAuthLogin:
    """Tests for user login endpoint."""

    def test_login_success(
        self, client: TestClient, override_get_db, override_auth_service: MagicMock
    ) -> None:
        """Test successful user login."""
        user_schema = UserSchema(
            id="test-id",
            name="Test User",
            email="test@example.com",
            username="testuser",
            is_verified=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        override_auth_service.login_user.return_value = (
            200,
            "access_token",
            "refresh_token",
            1800,  # expires_in (30 minutes)
            user_schema,
        )

        response = client.post(
            "/api/v1/auth/login",
            json={"identifier": "testuser", "password": "SecurePass123!"},
        )

        assert response.status_code == status.HTTP_200_OK

    def test_login_validation_error(
        self, client: TestClient, override_get_db, override_auth_service: MagicMock
    ) -> None:
        """Test login with invalid data."""
        # Mock return value in case validation passes (empty strings are technically valid)
        from app.exceptions.exceptions import InvalidCredentialsException

        override_auth_service.login_user.side_effect = InvalidCredentialsException(
            "Invalid credentials"
        )

        response = client.post(
            "/api/v1/auth/login",
            json={"identifier": "", "password": ""},
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestAuthVerification:
    """Tests for email verification endpoint."""

    def test_verify_user_success(
        self, client: TestClient, override_get_db, override_auth_service: MagicMock
    ) -> None:
        """Test successful user verification."""
        from app.modules.user_service.schema.user_schema import VerifyUserResponseSchema

        user_schema = UserSchema(
            id="test-id",
            name="Test User",
            email="test@example.com",
            username="testuser",
            is_verified=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        override_auth_service.verify_user.return_value = (
            200,
            VerifyUserResponseSchema(
                user=user_schema,
                tokens={"access_token": "test_token", "refresh_token": "test_refresh"},
            ),
        )

        response = client.post(
            "/api/v1/auth/verify",
            json={"identifier": "test@example.com", "verification_code": "123456"},
        )

        assert response.status_code == status.HTTP_200_OK


class TestAuthPasswordReset:
    """Tests for password reset endpoints."""

    def test_forgot_password_success(
        self, client: TestClient, override_get_db, override_auth_service: MagicMock
    ) -> None:
        """Test successful forgot password request."""
        from app.modules.user_service.schema.user_schema import GenericMessageSchema

        override_auth_service.forgot_password.return_value = (
            200,
            GenericMessageSchema(message="Reset code sent successfully"),
        )

        response = client.post(
            "/api/v1/auth/forgot-password",
            json={"identifier": "test@example.com"},
        )

        assert response.status_code == status.HTTP_200_OK

    def test_reset_password_success(
        self, client: TestClient, override_get_db, override_auth_service: MagicMock
    ) -> None:
        """Test successful password reset."""
        from app.modules.user_service.schema.user_schema import GenericMessageSchema

        override_auth_service.reset_password.return_value = (
            200,
            GenericMessageSchema(message="Password reset successfully"),
        )

        response = client.post(
            "/api/v1/auth/reset-password",
            json={
                "identifier": "test@example.com",
                "verification_code": "123456",
                "new_password": "NewSecurePass123!",
            },
        )

        assert response.status_code == status.HTTP_200_OK
