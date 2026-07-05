"""
Replay smoke test against the REAL golden workspace artifact checked into
crypalgos_core (tests/golden/workspace/), not the synthetic fixture used in
test_phase3_replay_api.py. Exercises the actual ReplayService with only the
S3 download stubbed.

Skips gracefully if the sibling crypalgos_core checkout isn't present at the
expected relative path (e.g. isolated CI checkouts of just this repo) — this
is a smoke test for local/monorepo development, not a hard CI dependency.
"""
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.modules.replay.services.replay_service import ReplayService

GOLDEN_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "../../../../crypalgos_core/tests/golden/workspace")
)

pytestmark = pytest.mark.skipif(
    not os.path.exists(os.path.join(GOLDEN_ROOT, "single_asset", "workspace.tar.zstd")),
    reason="sibling crypalgos_core golden workspace fixture not found — run "
           "generate_golden_workspace.py in crypalgos_core, or skip if this repo "
           "is checked out in isolation",
)


class FakeRunRepo:
    async def get_by_id(self, run_id):
        return SimpleNamespace(strategy_id="s1", artifact_manifest={"workspace": "golden/fixture"})


class FakeStrategyRepo:
    async def get_by_user_and_id(self, user_id, strategy_id):
        return object()


@pytest.fixture
def service():
    return ReplayService(FakeStrategyRepo(), FakeRunRepo())


def _golden_tar_bytes(name: str) -> bytes:
    return open(os.path.join(GOLDEN_ROOT, name, "workspace.tar.zstd"), "rb").read()


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["single_asset", "multi_asset", "compiled_conditions"])
async def test_full_replay_pipeline_against_golden_artifact(service, name):
    """The complete /session -> /window -> /trades/{id} -> /datasets flow,
    against a real Engine v2 artifact, not synthetic test data."""
    tar_bytes = _golden_tar_bytes(name)

    with patch(
        "app.modules.strategy_service.services.storage_service.storage_service.download_raw_payload",
        new=AsyncMock(return_value=tar_bytes),
    ):
        session = await service.get_session("u1", "run-golden")
        assert session["schema_version"] == 3
        assert session["bar_count"] > 0
        assert session["trade_count"] > 0
        # The core warmup gap this test caught: candle_index does NOT start
        # at 0 — the session must expose the real range explicitly.
        assert session["first_candle_index"] is not None
        assert session["first_candle_index"] > 0  # true for both golden strategies
        assert session["last_candle_index"] >= session["first_candle_index"]
        marker_types = {m["type"] for m in session["markers"]}
        assert "entry" in marker_types and "exit" in marker_types

        start = session["first_candle_index"]
        window = await service.get_window("u1", "run-golden", start, start + 49)
        assert window["candles"], "window at the real starting candle must return rows"
        assert window["candle_trees"], "window must return nested event trees"
        nested = [g for g in window["candle_trees"] if g["bar"] and g["bar"]["children"]]
        assert nested, "at least one candle in the window must have a nested decision tree"

        reader = await service._reader("u1", "run-golden")
        trades = await service._read_dataset(reader, "run-golden", "trades")
        assert trades, "golden strategies must produce at least one trade"
        trade_id = trades[0]["trade_id"]

        trade = await service.get_trade("u1", "run-golden", trade_id)
        assert trade["entry_event"]["type"] in ("POSITION_OPENED", "ORDER_FILLED")
        assert trade["exit_event"]["type"] in ("POSITION_CLOSED", "POSITION_REDUCED", "LIQUIDATION")
        assert trade["events"], "trade lifecycle must be non-empty"

        status, rows = await service.get_dataset_window(
            "u1", "run-golden", "indicator_snapshots", start, start + 20
        )
        assert status == 200
