"""Local-first archive for one testnet live-session workspace, finalized to
S3 on close() — same upload -> verify -> delete lifecycle as research run
artifacts (see ArtifactPaths, StorageService), so a live session's execution
record gets the same durability/debuggability guarantees as a backtest's."""

from __future__ import annotations

import json
import logging
import os
import shutil
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import msgpack
import pyarrow as pa
import pyarrow.parquet as pq

from app.config.settings import settings

logger = logging.getLogger(__name__)

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
    """A local archive write failed, so deterministic Testnet replay is no longer safe."""


class SessionWorkspaceArchive:
    """Persist testnet candles and engine events below one session directory,
    then finalize (upload + verify + delete local) on close()."""

    def __init__(
        self,
        strategy_id: str,
        session_id: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        self.strategy_id = strategy_id
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
        return Path(getattr(settings, "live_session_workspace_dir", "workspaces/live-sessions"))

    @classmethod
    def _session_dir(cls, session_id: str) -> Path:
        return cls._workspace_root() / session_id

    def _create_metadata(self, metadata: Mapping[str, Any] | None) -> None:
        if self.metadata_path.exists():
            return
        document = {
            "session_id": self.session_id,
            "strategy_id": self.strategy_id,
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

    async def close(self) -> dict[str, str] | None:
        """Finalize the workspace: upload every artifact that exists on
        local disk, verify each upload, delete the local directory only
        once every upload is confirmed, and return {section: s3_key}.

        Never deletes before every upload verifies. On any failure, the
        local directory is left completely untouched (not marked closed
        either) so a retry — explicit or the startup recovery sweep — can
        pick it back up. append_candles/append_events already write
        synchronously and fsync durably, so there is no separate "flush
        writers" step needed here.

        Idempotency on retry: every call re-uploads all three files that
        still exist locally, with no partial-completion tracking across
        calls — if the previous attempt got candles uploaded but failed on
        strategy_events, a retry re-uploads candles too, not just the one
        that failed. This is deliberate, not an oversight: S3 PUT to the
        same deterministic key (ArtifactPaths.live_candles/live_events/
        live_session_metadata, derived from strategy_id+session_id) always
        overwrites, so re-uploading unchanged local data is wasted bandwidth
        but never corrupts anything or produces a duplicate. The only side
        effect that matters -- deleting the local directory -- still only
        happens after *this* attempt's manifest is complete, so a session
        can be retried an unbounded number of times before it's ever
        actually archived."""
        if self._closed:
            return None

        self._stamp_closed_at()

        from app.modules.strategy_service.services.storage_service import (
            storage_service,
        )
        from app.utils.artifact_paths import ArtifactPaths

        paths = ArtifactPaths(
            strategy_id=self.strategy_id, run_id=self.session_id, kind="live-sessions"
        )
        uploads: dict[str, tuple[Path, str]] = {
            "candles": (self.candles_path, paths.live_candles),
            "strategy_events": (self.events_path, paths.live_events),
            "session_metadata": (self.metadata_path, paths.live_session_metadata),
        }

        manifest: dict[str, str] = {}
        for name, (local_path, s3_key) in uploads.items():
            if not local_path.exists():
                continue
            try:
                data = local_path.read_bytes()
                await storage_service.upload_raw_payload(s3_key, data)
                if not await storage_service.object_exists(s3_key, expected_size=len(data)):
                    raise SessionArchiveError(
                        f"Upload of {name} did not verify for session {self.session_id}"
                    )
                manifest[name] = s3_key
            except Exception:
                logger.exception(
                    "Failed to archive %s for session %s -- local workspace "
                    "kept intact for retry.",
                    name,
                    self.session_id,
                )
                return None

        shutil.rmtree(self.session_dir, ignore_errors=True)
        self._closed = True
        return manifest

    def _stamp_closed_at(self) -> None:
        try:
            document = (
                json.loads(self.metadata_path.read_text(encoding="utf-8"))
                if self.metadata_path.exists()
                else {"session_id": self.session_id}
            )
            document["closed_at"] = datetime.now().astimezone().isoformat()
            self.metadata_path.write_text(
                json.dumps(document, default=str, indent=2, sort_keys=True),
                encoding="utf-8",
            )
        except Exception:
            logger.exception(
                "Failed to stamp closed_at for session %s", self.session_id
            )

    @staticmethod
    async def read_candles(
        session_id: str, manifest: Mapping[str, str] | None = None
    ) -> list[list[float | int]]:
        """Local file if the session is still running (or archival hasn't
        happened yet); falls back to the archived S3 copy via `manifest`
        (LiveTradingSession.artifact_manifest) once the local workspace has
        been deleted."""
        candles_path = SessionWorkspaceArchive._session_dir(session_id) / "candles.parquet"
        if candles_path.exists():
            table = pq.read_table(candles_path).cast(CANDLE_SCHEMA)
            return SessionWorkspaceArchive._candles_table_to_rows(table)

        s3_key = (manifest or {}).get("candles")
        if not s3_key:
            return []
        from app.modules.strategy_service.services.storage_service import (
            storage_service,
        )

        raw = await storage_service.download_raw_payload(s3_key)
        table = pq.read_table(pa.BufferReader(raw)).cast(CANDLE_SCHEMA)
        return SessionWorkspaceArchive._candles_table_to_rows(table)

    @staticmethod
    def _candles_table_to_rows(table: pa.Table) -> list[list[float | int]]:
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
    async def read_events(
        session_id: str, manifest: Mapping[str, str] | None = None
    ) -> list[dict[str, Any]]:
        """Local file if present, else falls back to the archived S3 copy
        via `manifest` (LiveTradingSession.artifact_manifest)."""
        events_path = SessionWorkspaceArchive._session_dir(session_id) / "strategy_events.msgpack"
        if events_path.exists():
            with events_path.open("rb") as stream:
                unpacker = msgpack.Unpacker(stream, raw=False, strict_map_key=False)
                return [dict(record) for record in unpacker]

        s3_key = (manifest or {}).get("strategy_events")
        if not s3_key:
            return []
        from app.modules.strategy_service.services.storage_service import (
            storage_service,
        )

        raw = await storage_service.download_raw_payload(s3_key)
        unpacker = msgpack.Unpacker(raw=False, strict_map_key=False)
        unpacker.feed(raw)
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
