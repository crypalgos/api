"""Tests for strategy service routes."""

from datetime import datetime, UTC
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.modules.strategy_service.schema.strategy_schema import StrategyResponseSchema


def make_mock_strategy_schema(
    strategy_id: str = "test-strat-id",
    name: str = "Test Strategy",
    description: str = "A strategy for testing",
    canvas_json: dict = None,
    compiled_code: str = "class TestStrategy(StrategyBase): pass",
    is_code_modified: bool = False,
) -> StrategyResponseSchema:
    return StrategyResponseSchema(
        id=strategy_id,
        user_id="test-user-id",
        name=name,
        description=description,
        canvas_json=canvas_json or {"nodes": [], "edges": []},
        compiled_code=compiled_code,
        is_code_modified=is_code_modified,
        is_template=False,
        is_archived=False,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


class TestStrategyRoutes:
    """Tests for visual strategy route endpoints."""

    def test_create_strategy_success(
        self,
        client: TestClient,
        override_strategy_service: MagicMock,
        override_current_user,
    ) -> None:
        """Test successful visual strategy canvas creation."""
        mock_strategy = make_mock_strategy_schema()
        override_strategy_service.create_strategy.return_value = (201, mock_strategy)

        payload = {
            "name": "Test Strategy",
            "description": "A strategy for testing",
            "canvas_json": {"nodes": [], "edges": []},
        }

        response = client.post(
            "/api/v1/strategies",
            json=payload,
            headers={"Authorization": "Bearer test_token"},
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["data"]["id"] == "test-strat-id"
        override_strategy_service.create_strategy.assert_called_once_with(
            user_id="test-user-id",
            name="Test Strategy",
            description="A strategy for testing",
            canvas_json={"nodes": [], "edges": []},
        )

    def test_list_strategies_success(
        self,
        client: TestClient,
        override_strategy_service: MagicMock,
        override_current_user,
    ) -> None:
        """Test listing saved strategies for user."""
        mock_list = [
            make_mock_strategy_schema(strategy_id="strat-1"),
            make_mock_strategy_schema(strategy_id="strat-2"),
        ]
        from app.modules.strategy_service.schema.strategy_schema import (
            PaginatedStrategiesResponseSchema,
        )

        mock_paginated = PaginatedStrategiesResponseSchema(
            total=2, strategies=mock_list, current_page=1, limit=8, total_pages=1
        )
        override_strategy_service.list_strategies.return_value = (200, mock_paginated)

        response = client.get(
            "/api/v1/strategies", headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["data"]["total"] == 2
        assert len(response.json()["data"]["strategies"]) == 2
        assert response.json()["data"]["strategies"][0]["id"] == "strat-1"
        override_strategy_service.list_strategies.assert_called_once_with(
            user_id="test-user-id",
            page=1,
            limit=8,
            search="",
            is_template=None,
            archived=False,
        )

    def test_get_strategy_success(
        self,
        client: TestClient,
        override_strategy_service: MagicMock,
        override_current_user,
    ) -> None:
        """Test fetching a specific strategy."""
        mock_strat = make_mock_strategy_schema(strategy_id="strat-id-123")
        override_strategy_service.get_strategy.return_value = (200, mock_strat)

        response = client.get(
            "/api/v1/strategies/strat-id-123",
            headers={"Authorization": "Bearer test_token"},
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["data"]["id"] == "strat-id-123"
        override_strategy_service.get_strategy.assert_called_once_with(
            "test-user-id", "strat-id-123"
        )

    def test_save_monaco_code_success(
        self,
        client: TestClient,
        override_strategy_service: MagicMock,
        override_current_user,
    ) -> None:
        """Test saving custom edited Monaco code."""
        override_strategy_service.save_custom_code.return_value = (
            200,
            {
                "success": True,
                "message": "Custom Monaco code saved. Visual flow is desynchronized.",
            },
        )

        payload = {"code": "print('custom code')"}

        response = client.put(
            "/api/v1/strategies/strat-id-123/code",
            json=payload,
            headers={"Authorization": "Bearer test_token"},
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["data"]["success"] is True
        override_strategy_service.save_custom_code.assert_called_once_with(
            user_id="test-user-id",
            strategy_id="strat-id-123",
            code="print('custom code')",
        )

    def test_reset_to_visual_builder_success(
        self,
        client: TestClient,
        override_strategy_service: MagicMock,
        override_current_user,
    ) -> None:
        """Test resetting strategy state to visual builder canvas template sync."""
        mock_strat = make_mock_strategy_schema(
            strategy_id="strat-id-123", is_code_modified=False
        )
        override_strategy_service.reset_to_visual_builder.return_value = (
            200,
            mock_strat,
        )

        response = client.post(
            "/api/v1/strategies/strat-id-123/reset-builder",
            headers={"Authorization": "Bearer test_token"},
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["data"]["is_code_modified"] is False
        override_strategy_service.reset_to_visual_builder.assert_called_once_with(
            "test-user-id", "strat-id-123"
        )

    def test_execute_backtest_success(
        self,
        client: TestClient,
        override_strategy_service: MagicMock,
        override_current_user,
    ) -> None:
        """Test successfully enqueuing an institutional backtest run."""
        mock_response = {
            "status": "enqueued",
            "task_id": "celery-task-id-abc",
            "message": "Backtest enqueued successfully.",
        }
        override_strategy_service.trigger_backtest.return_value = (202, mock_response)

        payload = {
            "start_date": "2026-01-01T00:00:00Z",
            "end_date": "2026-01-02T00:00:00Z",
            "initial_capital": 10000.0,
        }

        response = client.post(
            "/api/v1/strategies/strat-id-123/backtests",
            json=payload,
            headers={"Authorization": "Bearer test_token"},
        )

        assert response.status_code == status.HTTP_202_ACCEPTED
        assert response.json()["data"]["status"] == "enqueued"
        assert response.json()["data"]["task_id"] == "celery-task-id-abc"

        # Verify the route correctly passes only dates+capital to the service
        # (exchange/symbol/leverage are now resolved internally by the service from canvas_json)
        called_args = override_strategy_service.trigger_backtest.call_args[1]
        assert called_args["user_id"] == "test-user-id"
        assert called_args["strategy_id"] == "strat-id-123"
        assert called_args["initial_capital"] == 10000.0
        assert isinstance(called_args["start_date"], datetime)
        assert isinstance(called_args["end_date"], datetime)
        # exchange/symbol/leverage NOT in called_args — they're resolved server-side
        assert "exchange" not in called_args
        assert "symbol" not in called_args
        assert "leverage" not in called_args
