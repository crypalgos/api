"""Synchronous local archive for one testnet live-session workspace."""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import msgpack
import pyarrow as pa
import pyarrow.parquet as pq

from app.config.settings import settings

CANDLE_SCHEMA = pa.schema(
    [
        pa.field("timestamp_ms", pa.int64(), nullable=False),
        pa.field("open", pa.float64(), nullable=False),
        pa.field("high", pa.float64(), nullable=False),
        pa.field("low", pa.float64(), nullable=False),
        pa.field("close", pa.float64(), nullable=False),
        pa.field("volume", pa.float64(), nullable=False),
    ]
)
_CANDLE_COLUMNS = ("timestamp_ms", "open", "high", "low", "close", "volume")


class SessionArchiveError(RuntimeError):
    """An archive write failed, so deterministic Testnet replay is no longer safe."""


class SessionWorkspaceArchive:
    """Persist testnet candles and engine events below one session directory."""

    def __init__(
        self, session_id: str, metadata: Mapping[str, Any] | None = None
    ) -> None:
        self.session_id = session_id
        self.session_dir = self._session_dir(session_id)
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.candles_path = self.session_dir / "candles.parquet"
        self.events_path = self.session_dir / "strategy_events.msgpack"
        self.metadata_path = self.session_dir / "session.json"
        self._closed = False
        self._create_metadata(metadata)

    @staticmethod
    def _workspace_root() -> Path:
        # The setting is added by deployment configuration. The fallback keeps
        # this isolated module importable in older local configurations.
        return Path(getattr(settings, "live_session_workspace_dir", "workspaces/live"))

    @classmethod
    def _session_dir(cls, session_id: str) -> Path:
        return cls._workspace_root() / session_id

    def _create_metadata(self, metadata: Mapping[str, Any] | None) -> None:
        if self.metadata_path.exists():
            return
        document = {
            "session_id": self.session_id,
            "created_at": datetime.now().astimezone().isoformat(),
            "archive_format": "testnet-workspace-v1",
        }
        if metadata:
            document.update(metadata)
        document["session_id"] = self.session_id
        self.metadata_path.write_text(
            json.dumps(document, default=str, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def append_candles(self, rows: Iterable[Sequence[Any]]) -> None:
        """Append complete OHLCV rows in canonical timestamp/open/.../volume order."""
        self._assert_open()
        normalized = [self._normalize_candle(row) for row in rows]
        if not normalized:
            return

        incoming = pa.Table.from_pydict(
            {
                name: [row[index] for row in normalized]
                for index, name in enumerate(_CANDLE_COLUMNS)
            },
            schema=CANDLE_SCHEMA,
        )
        table = incoming
        if self.candles_path.exists():
            existing = pq.read_table(self.candles_path).cast(CANDLE_SCHEMA)
            table = pa.concat_tables([existing, incoming])

        temporary_path = self.candles_path.with_name(
            f".{self.candles_path.name}.{uuid4().hex}.tmp"
        )
        try:
            pq.write_table(table, temporary_path, compression="zstd")
            os.replace(temporary_path, self.candles_path)
        finally:
            temporary_path.unlink(missing_ok=True)

    def append_candle(self, row: Sequence[Any]) -> None:
        """Append one complete `[timestamp_ms, open, high, low, close, volume]` row."""
        self.append_candles([row])

    def append_events(self, events: Iterable[Any]) -> None:
        """Append EngineEvent dictionaries as individually readable msgpack objects."""
        self._assert_open()
        records = [self._serialize_event(event) for event in events]
        if not records:
            return
        packer = msgpack.Packer(use_bin_type=True, default=self._msgpack_default)
        with self.events_path.open("ab") as stream:
            for record in records:
                stream.write(packer.pack(record))
            stream.flush()
            os.fsync(stream.fileno())

    def close(self) -> None:
        """Mark the archive closed; writes are synchronous and already durable."""
        self._closed = True

    @staticmethod
    def read_candles(session_id: str) -> list[list[float | int]]:
        candles_path = SessionWorkspaceArchive._session_dir(session_id) / "candles.parquet"
        if not candles_path.exists():
            return []
        table = pq.read_table(candles_path).cast(CANDLE_SCHEMA)
        columns = table.to_pydict()
        return [
            [
                int(columns["timestamp_ms"][index]),
                float(columns["open"][index]),
                float(columns["high"][index]),
                float(columns["low"][index]),
                float(columns["close"][index]),
                float(columns["volume"][index]),
            ]
            for index in range(table.num_rows)
        ]

    @staticmethod
    def read_events(session_id: str) -> list[dict[str, Any]]:
        events_path = SessionWorkspaceArchive._session_dir(session_id) / "strategy_events.msgpack"
        if not events_path.exists():
            return []
        with events_path.open("rb") as stream:
            unpacker = msgpack.Unpacker(stream, raw=False, strict_map_key=False)
            return [dict(record) for record in unpacker]

    @staticmethod
    def _normalize_candle(row: Sequence[Any]) -> list[float | int]:
        if len(row) != len(_CANDLE_COLUMNS):
            raise ValueError(
                "Candle rows must be [timestamp_ms, open, high, low, close, volume]"
            )
        return [int(row[0]), *(float(value) for value in row[1:])]

    @staticmethod
    def _serialize_event(event: Any) -> dict[str, Any]:
        to_dict = getattr(event, "to_dict", None)
        record = to_dict() if callable(to_dict) else event
        if not isinstance(record, Mapping):
            raise TypeError("Events must be EngineEvent instances or dictionaries")
        return dict(record)

    @staticmethod
    def _msgpack_default(value: Any) -> str:
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        return str(value)

    def _assert_open(self) -> None:
        if self._closed:
            raise RuntimeError("Cannot append to a closed session workspace archive")


TestnetSessionWorkspaceArchive = SessionWorkspaceArchive
