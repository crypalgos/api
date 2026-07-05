import logging
from dataclasses import dataclass, field
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

# Engine v2: exactly one supported artifact schema — no compatibility reads.
# Older runs are re-generated, not migrated.
REQUIRED_SCHEMA_VERSION = 2
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


@dataclass
class ReplayIndex:
    """O(1) lookup maps over a run's event stream, built in one pass.

    sequence_number -> event, candle_index -> events, and the marker list —
    no repeated scans anywhere downstream.
    """

    events: List[Dict[str, Any]]
    by_sequence: Dict[int, Dict[str, Any]] = field(default_factory=dict)
    by_candle: Dict[int, List[Dict[str, Any]]] = field(default_factory=dict)
    markers: List[Dict[str, Any]] = field(default_factory=list)
    symbols: List[str] = field(default_factory=list)

    @classmethod
    def build(cls, events: List[Dict[str, Any]]) -> "ReplayIndex":
        index = cls(events=events)
        symbols = set()
        for e in events:
            seq = e.get("sequence_number")
            if seq is not None:
                index.by_sequence[seq] = e
            candle = e.get("candle_index")
            if candle is not None:
                index.by_candle.setdefault(candle, []).append(e)
            if e.get("symbol_id"):
                symbols.add(e["symbol_id"])
            marker_type = _MARKER_TYPES.get(e.get("type"))
            if marker_type:
                index.markers.append({
                    "candle_index": candle,
                    "timestamp": e.get("timestamp"),
                    "type": marker_type,
                    "symbol_id": e.get("symbol_id"),
                    "sequence_number": seq,
                })
        index.symbols = sorted(symbols)
        return index

    def window(self, from_candle: int, to_candle: int) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for candle in range(from_candle, to_candle + 1):
            rows.extend(self.by_candle.get(candle, []))
        return rows

    def tree_at(self, candle_index: Optional[int]) -> Optional[Dict[str, Any]]:
        if candle_index is None:
            return None
        trees = build_candle_trees(self.by_candle.get(candle_index, []))
        return trees[0] if trees else None


class ReplayService:
    """Read-only replay API over immutable workspace artifacts.

    Replay never computes strategy logic — it validates, indexes, and nests
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
        if schema_version != REQUIRED_SCHEMA_VERSION:
            raise ValidationException(
                f"Workspace artifact schema v{schema_version} is not supported "
                f"(required: v{REQUIRED_SCHEMA_VERSION}). Re-run the backtest to "
                "regenerate the artifact."
            )
        return schema_version

    async def _read_dataset(
        self, reader: WorkspaceReader, run_id: str, dataset_name: str,
        optional: bool = False,
    ) -> List[Dict[str, Any]]:
        try:
            buf = await reader.get_dataset_bytes(dataset_name)
        except ResourceNotFoundException:
            if optional:
                return []
            raise
        try:
            return ArrowReader.read_all(buf)
        except Exception as e:
            logger.error(f"Corrupt dataset {dataset_name} for run {run_id}: {e}")
            raise ValidationException(
                f"Workspace artifact is corrupt: dataset '{dataset_name}' failed to decode."
            )

    async def _load_index(self, reader: WorkspaceReader, run_id: str) -> ReplayIndex:
        events = await self._read_dataset(reader, run_id, "runtime_events")
        return ReplayIndex.build(events)

    # ── Session ────────────────────────────────────────────────────────────

    async def get_session(self, user_id: str, run_id: str) -> dict:
        """Replay session bootstrap: validated manifest + timeline markers."""
        reader = await self._reader(user_id, run_id)
        manifest = await reader.get_manifest()
        schema_version = self._validate_manifest(manifest)

        index = await self._load_index(reader, run_id)
        dataset_ids = [d.get("dataset_id") for d in manifest.get("datasets", [])]

        return {
            "schema_version": schema_version,
            "engine_version": manifest.get("engine_version"),
            "created_at": manifest.get("created_at"),
            "bar_count": manifest.get("bar_count", 0),
            "trade_count": manifest.get("trade_count", 0),
            "indicator_count": manifest.get("indicator_count", 0),
            "symbols": index.symbols,
            "datasets": [d for d in dataset_ids if d in REPLAY_DATASETS],
            "markers": index.markers,
            "max_window_candles": MAX_REPLAY_WINDOW_CANDLES,
        }

    # ── Window ─────────────────────────────────────────────────────────────

    async def get_window(
        self, user_id: str, run_id: str, from_candle: int, to_candle: int
    ) -> dict:
        """One replay window: candles + pre-nested event trees + traces + indicators.
        The frontend reconstructs nothing."""
        self._validate_window(from_candle, to_candle)

        reader = await self._reader(user_id, run_id)
        manifest = await reader.get_manifest()
        schema_version = self._validate_manifest(manifest)

        candles_buf_rows = await self._read_windowed(reader, run_id, "candles", from_candle, to_candle, optional=True)
        decision_traces = await self._read_windowed(reader, run_id, "decision_traces", from_candle, to_candle, optional=True)
        indicators = await self._read_windowed(reader, run_id, "indicator_snapshots", from_candle, to_candle, optional=True)

        index = await self._load_index(reader, run_id)

        return {
            "schema_version": schema_version,
            "from_candle": from_candle,
            "to_candle": to_candle,
            "candles": candles_buf_rows,
            "candle_trees": build_candle_trees(index.window(from_candle, to_candle)),
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
        trades_by_id = {str(t.get("trade_id")): t for t in trades}
        trade = trades_by_id.get(str(trade_id))
        if trade is None:
            raise ResourceNotFoundException(f"Trade {trade_id} not found in this run.")

        index = await self._load_index(reader, run_id)

        entry_time = trade.get("entry_time")
        exit_time = trade.get("exit_time")
        lifecycle = [
            e for e in index.events
            if e.get("timestamp") is not None
            and entry_time is not None and exit_time is not None
            and entry_time <= e["timestamp"] <= exit_time
            and (e.get("symbol_id") in (None, trade.get("symbol")))
        ]

        candle_indexes = sorted({e["candle_index"] for e in lifecycle if e.get("candle_index") is not None})
        entry_candle = candle_indexes[0] if candle_indexes else None
        exit_candle = candle_indexes[-1] if candle_indexes else None

        indicators = await self._read_dataset(reader, run_id, "indicator_snapshots", optional=True)
        indicators_by_candle: Dict[int, List[Dict[str, Any]]] = {}
        for row in indicators:
            key = row.get("candle_index", row.get("bar_index"))
            if key is not None:
                indicators_by_candle.setdefault(key, []).append(row)

        return {
            "schema_version": schema_version,
            "trade": trade,
            "entry_candle": entry_candle,
            "exit_candle": exit_candle,
            "events": lifecycle,
            "entry_tree": index.tree_at(entry_candle),
            "exit_tree": index.tree_at(exit_candle),
            "indicators_at_entry": indicators_by_candle.get(entry_candle, []),
            "indicators_at_exit": indicators_by_candle.get(exit_candle, []),
        }

    # ── Single dataset (lazy panels) ───────────────────────────────────────

    async def get_dataset_window(
        self, user_id: str, run_id: str, dataset_name: str, start_bar: int, end_bar: int
    ) -> tuple[int, list]:
        """Windowed slice of a single allowlisted dataset."""
        if dataset_name not in REPLAY_DATASETS:
            raise ValidationException(
                f"Dataset '{dataset_name}' is not replayable. Allowed: {sorted(REPLAY_DATASETS)}"
            )
        self._validate_window(start_bar, end_bar)

        reader = await self._reader(user_id, run_id)
        rows = await self._read_windowed(reader, run_id, dataset_name, start_bar, end_bar)
        if dataset_name == "indicator_snapshots":
            for row in rows:
                if "source" in row:
                    row["datasource"] = row.pop("source")
        return 200, rows

    # ── Internals ──────────────────────────────────────────────────────────

    @staticmethod
    def _validate_window(from_candle: int, to_candle: int) -> None:
        if from_candle < 0 or to_candle < from_candle:
            raise ValidationException("Invalid window: require 0 <= from_candle <= to_candle.")
        if to_candle - from_candle + 1 > MAX_REPLAY_WINDOW_CANDLES:
            raise ValidationException(
                f"Window too large: max {MAX_REPLAY_WINDOW_CANDLES} candles per request."
            )

    async def _read_windowed(
        self, reader: WorkspaceReader, run_id: str, dataset_name: str,
        from_candle: int, to_candle: int, optional: bool = False,
    ) -> List[Dict[str, Any]]:
        try:
            buf = await reader.get_dataset_bytes(dataset_name)
        except ResourceNotFoundException:
            if optional:
                return []
            raise
        try:
            return ArrowReader.read_candle_window(buf, from_candle, to_candle)
        except Exception as e:
            logger.error(f"Corrupt dataset {dataset_name} for run {run_id}: {e}")
            raise ValidationException(
                f"Workspace artifact is corrupt: dataset '{dataset_name}' failed to decode."
            )
