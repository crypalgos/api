import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture  # type: ignore[misc]
def client() -> TestClient:
    """Create a test client for the FastAPI application."""
    return TestClient(app)


def test_root_endpoint(client: TestClient) -> None:
    """Test the health check endpoint returns the expected message."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "message": "API is running"}
