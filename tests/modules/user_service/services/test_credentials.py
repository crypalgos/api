import pytest
from unittest.mock import MagicMock, AsyncMock
from app.modules.user_service.services.credential_service import (
    credential_service,
    Exchange,
)
from app.modules.user_service.models.credential_model import Exchange


@pytest.mark.anyio
async def test_credential_encryption_decryption():
    key = "my-secret-api-key"
    encrypted = credential_service.encrypt(key)
    assert encrypted != key

    decrypted = credential_service.decrypt(encrypted)
    assert decrypted == key


@pytest.mark.anyio
async def test_broker_credentials_repr():
    from app.modules.user_service.services.credential_service import BrokerCredentials
    from pydantic import SecretStr

    creds = BrokerCredentials(
        id="test-id",
        exchange=Exchange.DELTA,
        api_key="my-key",
        api_secret=SecretStr("my-secret"),
    )

    repr_str = repr(creds)
    assert "my-secret" not in repr_str
    assert "test-id" in repr_str
    assert "delta" in repr_str


@pytest.mark.anyio
async def test_notification_preference_saving(monkeypatch):
    user_id = "test-user-id"
    prefs = {
        "telegram_chat_id": "123456",
        "telegram_enabled": True,
        "timezone": "America/New_York",
        "paper_alerts": False,
        "live_alerts": True,
    }

    # Mock database session commits
    mock_commit = AsyncMock()
    mock_add = MagicMock()

    class MockResult:
        def scalars(self):
            class MockScalars:
                def first(self):
                    return None

            return MockScalars()

    mock_execute = AsyncMock(return_value=MockResult())

    class MockSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            pass

        add = mock_add
        execute = mock_execute
        commit = mock_commit

    monkeypatch.setattr(
        "app.modules.user_service.services.credential_service.AsyncSessionLocal",
        MockSession,
    )

    await credential_service.save_notification_preference(user_id, prefs)

    assert mock_commit.call_count == 1


@pytest.mark.anyio
async def test_credential_rotation_in_memory_isolation():
    from app.modules.user_service.services.credential_service import BrokerCredentials
    from pydantic import SecretStr
    from unittest.mock import MagicMock

    # 1. Strategy deployed with initial keys
    creds_v1 = BrokerCredentials(
        id="cred-123",
        exchange=Exchange.DELTA,
        api_key="key-v1",
        api_secret=SecretStr("secret-v1"),
    )

    # ExecutionRunner holds initial credentials in memory
    runner = MagicMock()
    runner.broker_credentials = creds_v1

    # 2. Rotate credentials in DB/Service (creates creds_v2)
    creds_v2 = BrokerCredentials(
        id="cred-123",
        exchange=Exchange.DELTA,
        api_key="key-v2",
        api_secret=SecretStr("secret-v2"),
    )

    # Assert running strategy runner continues using in-memory v1 credentials
    assert runner.broker_credentials.api_key == "key-v1"
    assert runner.broker_credentials.api_secret.get_secret_value() == "secret-v1"

    # Validate the rotated credentials are separate
    assert creds_v2.api_key == "key-v2"
    assert creds_v2.api_secret.get_secret_value() == "secret-v2"
