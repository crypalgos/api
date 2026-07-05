import logging
from typing import Any, Dict, List, Optional

from crypalgos_core.pipeline.replay_tree import build_candle_trees

from app.exceptions.exceptions import ResourceNotFoundException, ValidationException
from app.modules.replay.utils.arrow_reader import ArrowReader
from app.modules.replay.utils.workspace_reader import WorkspaceReader
from app.modules.strategy_service.repositories.research_run_repository import (
    ResearchRunRepository,
)
from app.modules.strategy_service.repositories.strategy_repository import (
    StrategyRepository,
)

logger = logging.getLogger(__name__)

# Highest artifact schema this API knows how to serve
SUPPORTED_SCHEMA_VERSION = 2
# Hard limit per window request — the browser never loads more
MAX_REPLAY_WINDOW_CANDLES = 500

# Only these datasets are addressable through the replay API
REPLAY_DATASETS = frozenset(
    {"candles", "indicator_snapshots", "runtime_events", "decision_traces"}
)

# Runtime event types surfaced as timeline markers
_MARKER_TYPES = {
    "POSITION_OPENED": "entry",
    "POSITION_CLOSED": "exit",
    "POLICY_TRIGGERED": "policy",
    "LIQUIDATION": "liquidation",
}


def _normalize_event(row: Dict[str, Any]) -> Dict[str, Any]:
    """Reattach deprecated projections (correlation_id / parent_event_id) for
    the deprecation window. Derived, never stored (schema v2)."""
    parent = row.get("parent_sequence")
    root = row.get("root_sequence")
    if "parent_event_id" not in row:
        row["parent_event_id"] = str(parent) if parent is not None else None
    if "correlation_id" not in row:
        corr = root if root is not None else (parent if parent is not None else row.get("sequence_number"))
        row["correlation_id"] = str(corr) if corr is not None else None
    return row


class ReplayService:
    """Read-only replay API over immutable workspace artifacts.

    Replay never computes strategy logic — it validates, slices, and nests
    what execute_strategy() already produced.
    """

    def __init__(
        self,
        strategy_repository: StrategyRepository,
        run_repository: ResearchRunRepository,
    ):
        self.strategy_repository = strategy_repository
        self.run_repository = run_repository

    async def _resolve_workspace_key(self, user_id: str, run_id: str) -> str:
        run = await self.run_repository.get_by_id(run_id)
        if not run:
            raise ResourceNotFoundException("Research run not found")

        strategy = await self.strategy_repository.get_by_user_and_id(
            user_id, run.strategy_id
        )
        if not strategy:
            raise ResourceNotFoundException("Strategy not found")

        workspace_key = (
            run.artifact_manifest.get("workspace") if run.artifact_manifest else None
        )
        if not workspace_key:
            raise ResourceNotFoundException("Run dataset has no workspace key.")

        return workspace_key

    async def _reader(self, user_id: str, run_id: str) -> WorkspaceReader:
        return WorkspaceReader(await self._resolve_workspace_key(user_id, run_id))

    @staticmethod
    def _validate_manifest(manifest: dict) -> int:
        schema_version = int(manifest.get("schema_version", 1))
        if schema_version > SUPPORTED_SCHEMA_VERSION:
            raise ValidationException(
                f"Workspace artifact schema v{schema_version} is newer than this API "
                f"supports (v{SUPPORTED_SCHEMA_VERSION}). Upgrade the API."
            )
        return schema_version

    async def _read_dataset(
        self, reader: WorkspaceReader, run_id: str, dataset_name: str,
        from_candle: Optional[int] = None, to_candle: Optional[int] = None,
        optional: bool = False,
    ) -> List[Dict[str, Any]]:
        try:
            buf = await reader.get_dataset_bytes(dataset_name)
        except ResourceNotFoundException:
            if optional:
                return []
            raise
        try:
            if from_candle is None:
                return ArrowReader.read_all(buf)
            return ArrowReader.read_candle_window(buf, from_candle, to_candle)
        except Exception as e:
            logger.error(f"Corrupt dataset {dataset_name} for run {run_id}: {e}")
            raise ValidationException(
                f"Workspace artifact is corrupt: dataset '{dataset_name}' failed to decode."
            )

    # ── Session ────────────────────────────────────────────────────────────

    async def get_session(self, user_id: str, run_id: str) -> dict:
        """Replay session bootstrap: validated manifest + timeline markers."""
        reader = await self._reader(user_id, run_id)
        manifest = await reader.get_manifest()
        schema_version = self._validate_manifest(manifest)

        events = await self._read_dataset(reader, run_id, "runtime_events", optional=True)
        markers = [
            {
                "candle_index": e.get("candle_index"),
                "timestamp": e.get("timestamp"),
                "type": _MARKER_TYPES[e["type"]],
                "symbol_id": e.get("symbol_id"),
                "sequence_number": e.get("sequence_number"),
            }
            for e in events
            if e.get("type") in _MARKER_TYPES
        ]

        symbols = sorted({e["symbol_id"] for e in events if e.get("symbol_id")})
        dataset_ids = [d.get("dataset_id") for d in manifest.get("datasets", [])]

        return {
            "schema_version": schema_version,
            "engine_version": manifest.get("engine_version"),
            "created_at": manifest.get("created_at"),
            "bar_count": manifest.get("bar_count", 0),
            "trade_count": manifest.get("trade_count", 0),
            "indicator_count": manifest.get("indicator_count", 0),
            "deprecated_fields": manifest.get("deprecated_fields", []),
            "symbols": symbols,
            "datasets": [d for d in dataset_ids if d in REPLAY_DATASETS],
            "markers": markers,
            "max_window_candles": MAX_REPLAY_WINDOW_CANDLES,
        }

    # ── Window ─────────────────────────────────────────────────────────────

    async def get_window(
        self, user_id: str, run_id: str, from_candle: int, to_candle: int
    ) -> dict:
        """One replay window: candles + pre-nested event trees + traces + indicators.
        The frontend reconstructs nothing."""
        if from_candle < 0 or to_candle < from_candle:
            raise ValidationException("Invalid window: require 0 <= from_candle <= to_candle.")
        if to_candle - from_candle + 1 > MAX_REPLAY_WINDOW_CANDLES:
            raise ValidationException(
                f"Window too large: max {MAX_REPLAY_WINDOW_CANDLES} candles per request."
            )

        reader = await self._reader(user_id, run_id)
        manifest = await reader.get_manifest()
        schema_version = self._validate_manifest(manifest)

        candles = await self._read_dataset(reader, run_id, "candles", from_candle, to_candle, optional=True)
        runtime_events = await self._read_dataset(reader, run_id, "runtime_events", from_candle, to_candle)
        decision_traces = await self._read_dataset(reader, run_id, "decision_traces", from_candle, to_candle, optional=True)
        indicators = await self._read_dataset(reader, run_id, "indicator_snapshots", from_candle, to_candle, optional=True)

        runtime_events = [_normalize_event(e) for e in runtime_events]
        decision_traces = [_normalize_event(e) for e in decision_traces]

        return {
            "schema_version": schema_version,
            "from_candle": from_candle,
            "to_candle": to_candle,
            "candles": candles,
            "candle_trees": build_candle_trees(runtime_events),
            "decision_traces": decision_traces,
            "indicator_snapshots": indicators,
        }

    # ── Trade inspector ────────────────────────────────────────────────────

    async def get_trade(self, user_id: str, run_id: str, trade_id: str) -> dict:
        """Everything about one trade: lifecycle events + entry/exit decision trees."""
        reader = await self._reader(user_id, run_id)
        manifest = await reader.get_manifest()
        schema_version = self._validate_manifest(manifest)

        trades = await self._read_dataset(reader, run_id, "trades")
        trade = next((t for t in trades if str(t.get("trade_id")) == str(trade_id)), None)
        if trade is None:
            raise ResourceNotFoundException(f"Trade {trade_id} not found in this run.")

        entry_time = trade.get("entry_time")
        exit_time = trade.get("exit_time")

        events = await self._read_dataset(reader, run_id, "runtime_events")
        events = [_normalize_event(e) for e in events]

        lifecycle = [
            e for e in events
            if e.get("timestamp") is not None
            and entry_time is not None and exit_time is not None
            and entry_time <= e["timestamp"] <= exit_time
            and (e.get("symbol_id") in (None, trade.get("symbol")))
        ]

        candle_indexes = sorted({e["candle_index"] for e in lifecycle if e.get("candle_index") is not None})
        entry_candle = candle_indexes[0] if candle_indexes else None
        exit_candle = candle_indexes[-1] if candle_indexes else None

        def _tree_at(candle_index):
            if candle_index is None:
                return None
            group = [e for e in events if e.get("candle_index") == candle_index]
            trees = build_candle_trees(group)
            return trees[0] if trees else None

        indicators = await self._read_dataset(reader, run_id, "indicator_snapshots", optional=True)

        def _indicators_at(candle_index):
            if candle_index is None:
                return []
            return [
                r for r in indicators
                if r.get("candle_index", r.get("bar_index")) == candle_index
            ]

        return {
            "schema_version": schema_version,
            "trade": trade,
            "entry_candle": entry_candle,
            "exit_candle": exit_candle,
            "events": lifecycle,
            "entry_tree": _tree_at(entry_candle),
            "exit_tree": _tree_at(exit_candle),
            "indicators_at_entry": _indicators_at(entry_candle),
            "indicators_at_exit": _indicators_at(exit_candle),
        }

    # ── Single dataset (lazy panels + legacy paths) ────────────────────────

    async def get_manifest(self, user_id: str, run_id: str) -> tuple[int, dict]:
        """Legacy manifest endpoint — superseded by get_session."""
        session = await self.get_session(user_id, run_id)
        return 200, {
            "workspace_version": 1,
            "schema_version": session["schema_version"],
            "datasets": session["datasets"],
            "bar_count": session["bar_count"],
        }

    async def get_dataset_window(
        self, user_id: str, run_id: str, dataset_name: str, start_bar: int, end_bar: int
    ) -> tuple[int, list]:
        """Windowed slice of a single allowlisted dataset."""
        if dataset_name not in REPLAY_DATASETS:
            raise ValidationException(
                f"Dataset '{dataset_name}' is not replayable. Allowed: {sorted(REPLAY_DATASETS)}"
            )
        if end_bar < start_bar or start_bar < 0:
            raise ValidationException("Invalid window: require 0 <= start_bar <= end_bar.")
        if end_bar - start_bar + 1 > MAX_REPLAY_WINDOW_CANDLES:
            raise ValidationException(
                f"Window too large: max {MAX_REPLAY_WINDOW_CANDLES} candles per request."
            )

        reader = await self._reader(user_id, run_id)
        rows = await self._read_dataset(reader, run_id, dataset_name, start_bar, end_bar)
        if dataset_name in ("runtime_events", "decision_traces"):
            rows = [_normalize_event(r) for r in rows]
        if dataset_name == "indicator_snapshots":
            for row in rows:
                if "source" in row:
                    row["datasource"] = row.pop("source")
        return 200, rows
