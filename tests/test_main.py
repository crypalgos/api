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


def test_optimization_and_walkforward_detail_routes_are_registered() -> None:
    """Regression guard: both detail routes existed nowhere in the router table
    before this fix — the frontend called them, but they 404'd in production.
    A full authenticated round-trip needs DB/auth fixtures (see
    test_strategy_routes.py); this just asserts the routes are registered at
    all, which is the exact thing that was missing."""
    registered_get_paths = {
        route.path for route in app.routes if "GET" in getattr(route, "methods", set())
    }
    assert "/api/v1/strategies/{strategy_id}/optimizations/{run_id}" in registered_get_paths
    assert "/api/v1/strategies/{strategy_id}/walkforwards/{run_id}" in registered_get_paths
