"""Tests for user routes."""

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.main import app
from app.modules.user_service.schema.user_schema import (
    GenericMessageSchema,
    UserSchema,
)


@pytest.fixture
def client() -> TestClient:
    """Create a test client."""
    return TestClient(app)


@pytest.fixture
def mock_jwt_token() -> str:
    """Mock JWT token for authentication."""
    return "Bearer mock_jwt_token"


class TestGetCurrentUser:
    """Tests for getting current user profile endpoint."""

    def test_get_current_user_success(
        self,
        client: TestClient,
        override_get_db,
        override_user_service: MagicMock,
        override_current_user,
    ) -> None:
        """Test successful retrieval of current user."""

        user_schema = UserSchema(
            id="test-user-id",
            name="Test User",
            email="test@example.com",
            username="testuser",
            is_verified=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        async def mock_get_profile(*args, **kwargs):
            return 200, user_schema

        override_user_service.get_user_profile.side_effect = mock_get_profile

        response = client.get(
            "/api/v1/users/me", headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == status.HTTP_200_OK

    def test_get_current_user_unauthorized(
        self, client: TestClient, override_get_db, override_user_service: MagicMock
    ) -> None:
        """Test getting current user without authentication."""
        response = client.get("/api/v1/users/me")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestUpdateCurrentUser:
    """Tests for updating current user profile endpoint."""

    def test_update_current_user_success(
        self,
        client: TestClient,
        override_get_db,
        override_user_service: MagicMock,
        override_current_user,
    ) -> None:
        """Test successful update of current user."""

        user_schema = UserSchema(
            id="test-user-id",
            name="Updated Name",
            email="test@example.com",
            username="testuser",
            is_verified=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        async def mock_update_profile(*args, **kwargs):
            return 200, user_schema

        override_user_service.update_user_profile.side_effect = mock_update_profile

        response = client.put(
            "/api/v1/users/me",
            json={"name": "Updated Name"},
            headers={"Authorization": "Bearer test_token"},
        )

        assert response.status_code == status.HTTP_200_OK

    def test_update_current_user_unauthorized(
        self, client: TestClient, override_get_db, override_user_service: MagicMock
    ) -> None:
        """Test updating current user without authentication."""
        response = client.put("/api/v1/users/me", json={"name": "Updated User"})

        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestDeleteCurrentUser:
    """Tests for deleting current user account endpoint."""

    def test_delete_current_user_success(
        self,
        client: TestClient,
        override_get_db,
        override_user_service: MagicMock,
        override_current_user,
    ) -> None:
        """Test successful deletion of current user."""

        async def mock_delete_user(*args, **kwargs):
            return 200, GenericMessageSchema(message="User deleted successfully")

        override_user_service.delete_user_account.side_effect = mock_delete_user

        response = client.delete(
            "/api/v1/users/me", headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == status.HTTP_200_OK

    def test_delete_current_user_unauthorized(
        self, client: TestClient, override_get_db, override_user_service: MagicMock
    ) -> None:
        """Test deleting current user without authentication."""
        response = client.delete("/api/v1/users/me")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
