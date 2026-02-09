"""Test fixtures for user service tests."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.user_service.models.session_model import Session
from app.modules.user_service.models.user_model import User
from app.modules.user_service.repositories.session_repository import SessionRepository
from app.modules.user_service.repositories.user_repository import UserRepository
from app.modules.user_service.services.auth_service import AuthService
from app.modules.user_service.services.session_service import SessionService
from app.modules.user_service.services.user_service import UserService


@pytest.fixture
def mock_db_session() -> AsyncMock:
    """Create a mock database session."""
    session = AsyncMock(spec=AsyncSession)
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.refresh = AsyncMock()
    session.close = AsyncMock()

    # Mock execute to return a result with scalars()
    mock_result = AsyncMock()
    mock_scalars = MagicMock()
    mock_scalars.first = MagicMock(return_value=None)
    mock_scalars.all = MagicMock(return_value=[])
    mock_result.scalars = MagicMock(return_value=mock_scalars)
    session.execute = AsyncMock(return_value=mock_result)

    return session


@pytest.fixture
def sample_user() -> User:
    """Create a sample user for testing."""
    return User(
        id="test-user-id",
        name="Test User",
        email="test@example.com",
        username="testuser",
        password="$2b$12$hashed_password_here",
        is_verified=True,
        verification_code=None,
        verification_code_expiry=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


@pytest.fixture
def unverified_user() -> User:
    """Create an unverified user for testing."""
    return User(
        id="unverified-user-id",
        name="Unverified User",
        email="unverified@example.com",
        username="unverifieduser",
        password="$2b$12$hashed_password_here",
        is_verified=False,
        verification_code="123456",
        verification_code_expiry=datetime.now(UTC) + timedelta(minutes=10),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


@pytest.fixture
def sample_session(sample_user: User) -> Session:
    """Create a sample session for testing."""
    return Session(
        id="test-session-id",
        user_id=sample_user.id,
        refresh_token="sample_refresh_token",
        user_agent="Mozilla/5.0",
        ip_address="127.0.0.1",
        expires_at=datetime.now(UTC) + timedelta(days=7),
        created_at=datetime.now(UTC),
    )


@pytest.fixture
def mock_user_repository(mock_db_session: AsyncMock) -> MagicMock:
    """Create a mock user repository."""
    repo = MagicMock(spec=UserRepository)
    repo.session = mock_db_session
    # Pre-configure common async methods as AsyncMock
    repo.get_by_id = AsyncMock(return_value=None)
    repo.get_by_email = AsyncMock(return_value=None)
    repo.get_by_username = AsyncMock(return_value=None)
    repo.get_by_identifier = AsyncMock(return_value=None)
    repo.create_user = AsyncMock(return_value=None)
    repo.update_user = AsyncMock(return_value=None)
    repo.delete_user = AsyncMock(return_value=None)
    return repo


@pytest.fixture
def mock_session_repository(mock_db_session: AsyncMock) -> MagicMock:
    """Create a mock session repository."""
    repo = MagicMock(spec=SessionRepository)
    repo.session = mock_db_session
    # Pre-configure common async methods as AsyncMock
    repo.create_session = AsyncMock(return_value=None)
    repo.get_by_refresh_token = AsyncMock(return_value=None)
    repo.get_user_sessions = AsyncMock(return_value=[])
    repo.delete = AsyncMock(return_value=None)
    repo.delete_user_sessions = AsyncMock(return_value=None)
    repo.cleanup_expired_sessions = AsyncMock(return_value=None)
    repo.enforce_session_limit = AsyncMock(return_value=None)
    return repo


@pytest.fixture
def auth_service(
    mock_user_repository: UserRepository, mock_session_repository: SessionRepository
) -> AuthService:
    """Create an auth service with mock repositories."""
    return AuthService(mock_user_repository, mock_session_repository)


@pytest.fixture
def session_service(
    mock_session_repository: SessionRepository, mock_user_repository: UserRepository
) -> SessionService:
    """Create a session service with mock repositories."""
    return SessionService(mock_session_repository, mock_user_repository)


@pytest.fixture
def user_service(mock_user_repository: UserRepository) -> UserService:
    """Create a user service with mock repository."""
    return UserService(mock_user_repository)
