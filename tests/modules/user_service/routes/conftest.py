"""Shared fixtures for route tests."""

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.connect_db import get_db
from app.main import app
from app.modules.user_service.routes.auth_routes import get_auth_service
from app.middlewares.auth_middleware import get_current_user
from app.modules.user_service.routes.session_routes import (
    get_current_user_data,
)
from app.modules.user_service.routes.session_routes import get_session_service
from app.modules.user_service.routes.user_routes import get_user_service


@pytest.fixture
def mock_db_session() -> AsyncMock:
    """Create a mock database session for route tests."""
    session = AsyncMock(spec=AsyncSession)
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.close = AsyncMock()
    return session


@pytest.fixture
def mock_auth_service() -> MagicMock:
    """Create a mock auth service."""
    service = MagicMock()
    # Pre-configure all async methods
    service.register_user = AsyncMock()
    service.login_user = AsyncMock()
    service.verify_user = AsyncMock()
    service.resend_verification_code = AsyncMock()
    service.check_verification_code = AsyncMock()
    service.forgot_password = AsyncMock()
    service.reset_password = AsyncMock()
    service.refresh_token = AsyncMock()
    service.logout = AsyncMock()
    return service


@pytest.fixture
def mock_user_service() -> MagicMock:
    """Create a mock user service."""
    service = MagicMock()
    service.get_user_profile = AsyncMock()
    service.update_user_profile = AsyncMock()
    service.delete_user_account = AsyncMock()
    return service


@pytest.fixture
def mock_session_service() -> MagicMock:
    """Create a mock session service."""
    service = MagicMock()
    service.get_user_sessions = AsyncMock()
    service.delete_session = AsyncMock()
    service.delete_all_sessions = AsyncMock()
    service.cleanup_expired_sessions = AsyncMock()
    return service


@pytest.fixture
def override_get_db(mock_db_session: AsyncMock):
    """Override the get_db dependency to return mock session."""

    async def _get_db_override() -> AsyncGenerator[AsyncSession, None]:
        yield mock_db_session

    app.dependency_overrides[get_db] = _get_db_override
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def override_auth_service(mock_auth_service: MagicMock):
    """Override the auth service dependency."""

    async def _get_auth_service_override():
        return mock_auth_service

    app.dependency_overrides[get_auth_service] = _get_auth_service_override
    yield mock_auth_service
    if get_auth_service in app.dependency_overrides:
        del app.dependency_overrides[get_auth_service]


@pytest.fixture
def override_user_service(mock_user_service: MagicMock):
    """Override the user service dependency."""

    async def _get_user_service_override():
        return mock_user_service

    app.dependency_overrides[get_user_service] = _get_user_service_override
    yield mock_user_service
    if get_user_service in app.dependency_overrides:
        del app.dependency_overrides[get_user_service]


@pytest.fixture
def override_session_service(mock_session_service: MagicMock):
    """Override the session service dependency."""

    async def _get_session_service_override():
        return mock_session_service

    app.dependency_overrides[get_session_service] = _get_session_service_override
    yield mock_session_service
    if get_session_service in app.dependency_overrides:
        del app.dependency_overrides[get_session_service]


@pytest.fixture
def override_current_user():
    """Override the get_current_user and get_current_user_data dependencies."""

    async def _get_current_user_override():
        return {"user_id": "test-user-id"}

    async def _get_current_user_data_override():
        return "test-user-id", "test-refresh-token"

    # Override for both user and session routes
    app.dependency_overrides[get_current_user] = _get_current_user_override
    app.dependency_overrides[get_current_user_data] = _get_current_user_data_override

    yield "test-user-id"

    if get_current_user in app.dependency_overrides:
        del app.dependency_overrides[get_current_user]
    if get_current_user_data in app.dependency_overrides:
        del app.dependency_overrides[get_current_user_data]
