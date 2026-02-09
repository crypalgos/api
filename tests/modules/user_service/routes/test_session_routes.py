"""Tests for session routes."""

from unittest.mock import MagicMock

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.main import app
from app.modules.user_service.schema.user_schema import (
    GenericMessageSchema,
)


@pytest.fixture
def client() -> TestClient:
    """Create a test client."""
    return TestClient(app)


@pytest.fixture
def mock_jwt_token() -> str:
    """Mock JWT token for authentication."""
    return "Bearer mock_jwt_token"


class TestGetUserSessions:
    """Tests for getting user sessions endpoint."""

    def test_get_sessions_success(
        self,
        client: TestClient,
        override_get_db,
        override_session_service: MagicMock,
        override_current_user,
    ) -> None:
        """Test successful retrieval of user sessions."""
        from datetime import UTC, datetime

        from app.modules.user_service.schema.session_schema import SessionSchema

        sessions = [
            SessionSchema(
                id="session-1",
                user_id="test-user-id",
                ip_address="127.0.0.1",
                user_agent="Test Agent",
                refresh_token_hash="hash1",
                expires_at=datetime.now(UTC),
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        ]
        override_session_service.get_user_sessions.return_value = (200, sessions)

        response = client.get(
            "/api/v1/sessions", headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == status.HTTP_200_OK

    def test_get_sessions_unauthorized(
        self, client: TestClient, override_get_db, override_session_service: MagicMock
    ) -> None:
        """Test getting sessions without authentication."""
        response = client.get("/api/v1/sessions/")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestDeleteSession:
    """Tests for deleting a specific session endpoint."""

    def test_delete_session_success(
        self,
        client: TestClient,
        override_get_db,
        override_session_service: MagicMock,
        override_current_user,
    ) -> None:
        """Test successful session deletion."""

        override_session_service.delete_session.return_value = (
            200,
            GenericMessageSchema(message="Session deleted successfully"),
        )

        response = client.delete(
            "/api/v1/sessions/session-id",
            headers={"Authorization": "Bearer test_token"},
        )

        assert response.status_code == status.HTTP_200_OK

    def test_delete_session_unauthorized(
        self, client: TestClient, override_get_db, override_session_service: MagicMock
    ) -> None:
        """Test deleting session without authentication."""
        response = client.delete("/api/v1/sessions/session-id")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestDeleteAllSessions:
    """Tests for deleting all sessions endpoint."""

    def test_delete_all_sessions_success(
        self,
        client: TestClient,
        override_get_db,
        override_session_service: MagicMock,
        override_current_user,
    ) -> None:
        """Test successful deletion of all sessions."""

        override_session_service.delete_all_sessions.return_value = (
            200,
            GenericMessageSchema(message="All sessions deleted successfully"),
        )

        response = client.delete(
            "/api/v1/sessions", headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == status.HTTP_200_OK



