"""Tests for contact messages routes."""

from datetime import UTC, datetime
from app.middlewares.auth_middleware import CurrentUser
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.main import app
from app.modules.user_service.routes.contact_routes import get_contact_service
from app.middlewares.auth_middleware import get_admin_user
from app.modules.user_service.schema.contact_schema import ContactResponseSchema
from app.modules.user_service.schema.user_schema import GenericMessageSchema


@pytest.fixture
def client() -> TestClient:
    """Create a test client."""
    return TestClient(app)


@pytest.fixture
def mock_contact_service() -> MagicMock:
    """Create a mock contact service."""
    service = MagicMock()
    service.create_message = AsyncMock()
    service.get_all_messages = AsyncMock()
    service.delete_message = AsyncMock()
    return service


@pytest.fixture
def override_contact_service(mock_contact_service: MagicMock):
    """Override the contact service dependency."""

    async def _get_contact_service_override():
        return mock_contact_service

    app.dependency_overrides[get_contact_service] = _get_contact_service_override
    yield mock_contact_service
    if get_contact_service in app.dependency_overrides:
        del app.dependency_overrides[get_contact_service]


@pytest.fixture
def override_admin_user():
    """Override the get_admin_user dependency to return a mock admin."""

    async def _get_admin_user_override():
        return CurrentUser(user_id="admin-id", email="ashishjangde54@gmail.com")

    app.dependency_overrides[get_admin_user] = _get_admin_user_override
    yield
    if get_admin_user in app.dependency_overrides:
        del app.dependency_overrides[get_admin_user]


class TestContactSubmit:
    """Tests for contact message submission endpoint."""

    def test_submit_success(
        self, client: TestClient, override_contact_service: MagicMock
    ) -> None:
        """Test successful submission of a contact message."""
        mock_response = ContactResponseSchema(
            id="test-contact-id",
            name="Alice Smith",
            email="alice@example.com",
            subject="Integration issue",
            message="I am unable to bind my exchange API key.",
            created_at=datetime.now(UTC),
        )
        override_contact_service.create_message.return_value = (201, mock_response)

        response = client.post(
            "/api/v1/contact",
            json={
                "name": "Alice Smith",
                "email": "alice@example.com",
                "subject": "Integration issue",
                "message": "I am unable to bind my exchange API key.",
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["data"]["name"] == "Alice Smith"
        assert data["data"]["email"] == "alice@example.com"
        assert data["data"]["subject"] == "Integration issue"
        assert data["data"]["message"] == "I am unable to bind my exchange API key."

    def test_submit_validation_error(self, client: TestClient) -> None:
        """Test validation error for contact message submission."""
        # Missing message and invalid email
        response = client.post(
            "/api/v1/contact",
            json={
                "name": "Alice Smith",
                "email": "not-an-email",
            },
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


class TestContactAdminActions:
    """Tests for admin contact panel actions (retrieval and resolution)."""

    def test_get_messages_as_admin(
        self,
        client: TestClient,
        override_contact_service: MagicMock,
        override_admin_user,
    ) -> None:
        """Test admin retrieving contact messages."""
        mock_data = {
            "items": [
                {
                    "id": "1",
                    "name": "Alice Smith",
                    "email": "alice@example.com",
                    "subject": "Exchange",
                    "message": "Key binding failed",
                    "created_at": datetime.now(UTC).isoformat(),
                }
            ],
            "total": 1,
            "limit": 10,
            "offset": 0,
        }
        override_contact_service.get_all_messages.return_value = (200, mock_data)

        # Include Authorization header to satisfy security Bearer scheme dependency
        response = client.get(
            "/api/v1/contact?limit=10&offset=0",
            headers={"Authorization": "Bearer mock-token"},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["data"]["total"] == 1
        assert data["data"]["items"][0]["name"] == "Alice Smith"

    def test_resolve_message_as_admin(
        self,
        client: TestClient,
        override_contact_service: MagicMock,
        override_admin_user,
    ) -> None:
        """Test admin resolving (deleting) a contact message."""
        override_contact_service.delete_message.return_value = (
            200,
            GenericMessageSchema(message="Contact message deleted successfully"),
        )

        response = client.delete(
            "/api/v1/contact/test-msg-id",
            headers={"Authorization": "Bearer mock-token"},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "deleted successfully" in data["data"]["message"]
