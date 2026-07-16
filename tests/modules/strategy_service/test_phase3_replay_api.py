"""
Phase 3 gate — T-REPLAY-3..8: replay session/window/trade endpoints served
from immutable artifacts, with strict bounds and error semantics.

Uses a fake WorkspaceReader backed by REAL Arrow bytes (typed v2 envelope for
events), so the full decode path is exercised without S3.
"""
import io
import json
from types import SimpleNamespace

import pyarrow as pa
import pytest

from crypalgos_core.events.arrow_schemas import events_to_arrow_table

from app.exceptions.exceptions import ResourceNotFoundException, ValidationException
from app.modules.replay.services import replay_service as svc_mod
from app.modules.replay.services.replay_service import (
    MAX_REPLAY_WINDOW_CANDLES,
    ReplayService,
)


# ── Fake artifact data ──────────────────────────────────────────────────────

def _event(seq, candle, etype, parent=None, root=None, payload=None, ts=None, symbol="BTCUSD"):
    return {
        "sequence_number": seq,
        "timestamp": ts if ts is not None else 1_000_000 + candle * 60_000,
        "candle_index": candle,
        "symbol_id": symbol,
        "type": etype,
        "parent_sequence": parent,
        "root_sequence": root,
        "node_id": None,
        "run_id": "run-1",
        "strategy_id": "Golden",
        "payload": payload or {},
    }


EVENTS = [
    # candle 0: bar -> condition(fail) -> snapshot
    _event(1, 0, "BAR_CLOSED", root=1, payload={"open": 1.0, "close": 2.0}),
    _event(2, 0, "CONDITION_EVALUATED", parent=1, root=1,
           payload={"condition_id": "c1", "passed": False,
                    "inputs": {"EMA(9)": 1.0}, "expression": "EMA(9) > 2"}),
    _event(3, 0, "PORTFOLIO_SNAPSHOT", parent=1, root=1, payload={"equity": 10000.0}),
    # candle 1: bar -> condition -> action -> order; fill+open at candle 2
    _event(4, 1, "BAR_CLOSED", root=4),
    _event(5, 1, "CONDITION_EVALUATED", parent=4, root=4, payload={"passed": True}),
    _event(6, 1, "ACTION_TRIGGERED", parent=5, root=4, payload={"action_id": "a1"}),
    _event(7, 1, "ORDER_CREATED", parent=6, root=4, payload={"order_id": "o1"}),
    _event(8, 2, "ORDER_FILLED", parent=7, root=4, payload={"order_id": "o1"}),
    _event(9, 2, "POSITION_OPENED", parent=8, root=4, payload={"position_id": "p1"}),
    _event(10, 2, "BAR_CLOSED", root=10),
    # candle 3: close the trade
    _event(11, 3, "BAR_CLOSED", root=11),
    _event(12, 3, "POSITION_CLOSED", parent=11, root=11, payload={"realized_pnl": 5.0}),
]

CANDLES = [
    {"candle_index": i, "timestamp": 1_000_000 + i * 60_000, "symbol": "BTCUSD",
     "timeframe": "1h", "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 10.0}
    for i in range(4)
]

TRADES = [{
    "trade_id": "t-1", "symbol": "BTCUSD", "side": "long",
    "entry_time": 1_000_000 + 2 * 60_000, "exit_time": 1_000_000 + 3 * 60_000,
    "net_pnl": 5.0,
    # Engine v2: trades point into the event stream — no reason blobs
    "entry_sequence": 9,   # POSITION_OPENED at candle 2
    "exit_sequence": 12,   # POSITION_CLOSED at candle 3
}]

INDICATORS = [
    {"candle_index": i, "timestamp": 1_000_000 + i * 60_000, "values": json.dumps({"EMA(9)": 1.0 + i})}
    for i in range(4)
]


def _table_bytes(table: pa.Table) -> bytes:
    sink = io.BytesIO()
    with pa.RecordBatchFileWriter(sink, table.schema) as writer:
        writer.write_table(table)
    return sink.getvalue()


def _manifest(schema_version=3):
    return {
        "schema_version": schema_version,
        "engine_version": "2.0.0",
        "created_at": "2026-07-05T00:00:00Z",
        "bar_count": len(CANDLES),
        "trade_count": len(TRADES),
        "indicator_count": len(INDICATORS),
        "datasets": [
            {"dataset_id": name} for name in
            ("candles", "runtime_events", "decision_traces", "indicator_snapshots", "trades")
        ],
    }


def _dataset_bytes():
    decision_events = [e for e in EVENTS if e["type"].startswith(("CONDITION", "ACTION"))]
    return {
        "candles": _table_bytes(pa.Table.from_pylist(CANDLES)),
        "runtime_events": _table_bytes(events_to_arrow_table(EVENTS)),
        "decision_traces": _table_bytes(events_to_arrow_table(decision_events)),
        "indicator_snapshots": _table_bytes(pa.Table.from_pylist(INDICATORS)),
        "trades": _table_bytes(pa.Table.from_pylist(TRADES)),
    }


class FakeWorkspaceReader:
    manifest = _manifest()
    datasets = _dataset_bytes()

    def __init__(self, workspace_key):
        pass

    async def get_manifest(self):
        return self.manifest

    async def get_dataset_bytes(self, name):
        if name not in self.datasets:
            raise ResourceNotFoundException(f"Dataset {name} not found in manifest")
        return self.datasets[name]


class FakeRunRepo:
    async def get_by_id(self, run_id):
        return SimpleNamespace(strategy_id="s1", artifact_manifest={"workspace": "s3://x"})


class FakeStrategyRepo:
    async def get_by_user_and_id(self, user_id, strategy_id):
        return object()


@pytest.fixture
def service(monkeypatch):
    monkeypatch.setattr(svc_mod, "WorkspaceReader", FakeWorkspaceReader)
    FakeWorkspaceReader.manifest = _manifest()
    return ReplayService(FakeStrategyRepo(), FakeRunRepo())


# ── T-REPLAY-6: session ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_session_contents(service):
    session = await service.get_session("u1", "r1")
    assert session["schema_version"] == 3
    assert session["bar_count"] == 4
    assert session["trade_count"] == 1
    assert session["symbols"] == ["BTCUSD"]
    assert session["max_window_candles"] == MAX_REPLAY_WINDOW_CANDLES
    # Callers must window against the real candle range, not [0, bar_count-1] —
    # indicator warmup means candle_index rarely starts at 0 in production.
    assert session["first_candle_index"] == 0
    assert session["last_candle_index"] == 3

    markers = {(m["type"], m["candle_index"]) for m in session["markers"]}
    assert ("entry", 2) in markers
    assert ("exit", 3) in markers


@pytest.mark.asyncio
async def test_session_rejects_wrong_schema(service):
    """Engine v3: exactly one supported schema — both older and newer rejected."""
    for bad_version in (1, 99):
        FakeWorkspaceReader.manifest = _manifest(schema_version=bad_version)
        with pytest.raises(ValidationException, match="not supported"):
            await service.get_session("u1", "r1")


# ── T-REPLAY-3/4: window ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_window_filters_by_candle_index_and_nests(service):
    window = await service.get_window("u1", "r1", 1, 2)

    assert [c["candle_index"] for c in window["candles"]] == [1, 2]

    trees = {g["candle_index"]: g for g in window["candle_trees"]}
    assert set(trees) == {1, 2}

    # candle 1: bar -> condition -> action -> order, fully nested
    bar = trees[1]["bar"]
    assert bar["sequence_number"] == 4
    cond = bar["children"][0]
    assert cond["type"] == "CONDITION_EVALUATED"
    action = cond["children"][0]
    assert action["type"] == "ACTION_TRIGGERED"
    order = action["children"][0]
    assert order["type"] == "ORDER_CREATED"

    # zero-lookahead: the fill (candle 2) nests causally under its order (candle 1)
    fill = order["children"][0]
    assert fill["type"] == "ORDER_FILLED" and fill["candle_index"] == 2

    # payload decoded from the typed Arrow column
    assert cond["payload"]["passed"] is True


@pytest.mark.asyncio
async def test_window_orphans_preserved_at_window_edge(service):
    """A fill whose parent order falls outside the window is kept as an orphan."""
    window = await service.get_window("u1", "r1", 2, 2)
    trees = {g["candle_index"]: g for g in window["candle_trees"]}
    orphan_seqs = {o["sequence_number"] for o in trees[2]["orphans"]}
    assert 8 in orphan_seqs  # ORDER_FILLED, parent seq 7 not in window


@pytest.mark.asyncio
async def test_window_events_have_no_shim_fields(service):
    """Engine v2: linkage is parent_sequence/root_sequence ints — nothing else."""
    window = await service.get_window("u1", "r1", 0, 0)
    cond = window["candle_trees"][0]["bar"]["children"][0]
    assert cond["parent_sequence"] == 1
    assert cond["root_sequence"] == 1
    assert "correlation_id" not in cond
    assert "parent_event_id" not in cond
    assert "id" not in cond


@pytest.mark.asyncio
async def test_window_bounds(service):
    with pytest.raises(ValidationException, match="Window too large"):
        await service.get_window("u1", "r1", 0, MAX_REPLAY_WINDOW_CANDLES)
    with pytest.raises(ValidationException, match="Invalid window"):
        await service.get_window("u1", "r1", 5, 2)
    with pytest.raises(ValidationException, match="Invalid window"):
        await service.get_window("u1", "r1", -1, 2)


# ── T-REPLAY-7: trade inspector ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_trade_endpoint(service):
    result = await service.get_trade("u1", "r1", "t-1")
    assert result["trade"]["trade_id"] == "t-1"
    # O(1) pointer resolution — candles come from the pointed events
    assert result["entry_event"]["type"] == "POSITION_OPENED"
    assert result["exit_event"]["type"] == "POSITION_CLOSED"
    assert result["entry_candle"] == 2
    assert result["exit_candle"] == 3
    # lifecycle = sequence range [entry_sequence, exit_sequence]
    seqs = [e["sequence_number"] for e in result["events"]]
    assert min(seqs) == 9 and max(seqs) == 12
    assert "POSITION_CLOSED" in [e["type"] for e in result["events"]]
    assert result["exit_tree"]["bar"]["children"][0]["type"] == "POSITION_CLOSED"
    assert result["indicators_at_entry"][0]["candle_index"] == 2


@pytest.mark.asyncio
async def test_trade_without_pointers_is_422(service, monkeypatch):
    """Artifacts whose trades lack event pointers must be regenerated — never guessed."""
    broken = dict(TRADES[0])
    broken.pop("entry_sequence"); broken.pop("exit_sequence")
    FakeWorkspaceReader.datasets = dict(FakeWorkspaceReader.datasets)
    FakeWorkspaceReader.datasets["trades"] = _table_bytes(pa.Table.from_pylist([broken]))
    try:
        with pytest.raises(ValidationException, match="pointers"):
            await service.get_trade("u1", "r1", "t-1")
    finally:
        FakeWorkspaceReader.datasets = _dataset_bytes()


@pytest.mark.asyncio
async def test_trade_not_found_is_404(service):
    with pytest.raises(ResourceNotFoundException):
        await service.get_trade("u1", "r1", "nope")


# ── T-REPLAY-8: dataset allowlist ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_dataset_allowlist(service):
    with pytest.raises(ValidationException, match="not replayable"):
        await service.get_dataset_window("u1", "r1", "portfolio_equity", 0, 10)
    with pytest.raises(ValidationException, match="not replayable"):
        await service.get_dataset_window("u1", "r1", "../secrets", 0, 10)

    status, rows = await service.get_dataset_window("u1", "r1", "candles", 0, 1)
    assert status == 200
    assert [r["candle_index"] for r in rows] == [0, 1]


@pytest.mark.asyncio
async def test_dataset_window_bound(service):
    with pytest.raises(ValidationException, match="Window too large"):
        await service.get_dataset_window("u1", "r1", "candles", 0, MAX_REPLAY_WINDOW_CANDLES + 10)
