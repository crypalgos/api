"""Timeline data-source abstractions for testnet archives and production storage."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Protocol

from app.modules.strategy_service.services.session_workspace_archive import (
    SessionWorkspaceArchive,
)

if TYPE_CHECKING:
    from app.modules.strategy_service.repositories.strategy_event_repository import (
        StrategyEventRepository,
    )


class TimelineDataSource(Protocol):
    """Supplies timeline events and OHLCV candles for one live session."""

    async def load_timeline(self) -> dict[str, Any]: ...

    async def load_candles(self) -> list[list[float | int]]: ...


class TestnetTimelineDataSource:
    """Reads a Testnet session's archive -- the local workspace while it's
    still running (or before archival completes), the S3-uploaded copy via
    `artifact_manifest` once SessionWorkspaceArchive.close() has deleted the
    local files."""

    def __init__(
        self, session_id: str, artifact_manifest: Mapping[str, str] | None = None
    ) -> None:
        self.session_id = session_id
        self.artifact_manifest = artifact_manifest

    async def load_timeline(
        self,
        *,
        since: datetime | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        raw_events = await SessionWorkspaceArchive.read_events(
            self.session_id, self.artifact_manifest
        )
        events = [
            _archive_event_to_timeline(event, self.session_id, index)
            for index, event in enumerate(raw_events)
        ]
        if since is not None:
            cutoff = _as_utc_datetime(since)
            events = [
                event
                for event in events
                if (created_at := _as_utc_datetime(event["created_at"])) is None
                or created_at > cutoff
            ]
        if limit is not None:
            events = events[-limit:]
        return {"session_id": self.session_id, "events": events}

    async def load_candles(self) -> list[list[float | int]]:
        return await SessionWorkspaceArchive.read_candles(
            self.session_id, self.artifact_manifest
        )


class ProductionTimelineDataSource:
    """Reads durable events from Postgres and candles from ClickHouse."""

    def __init__(
        self,
        session_id: str,
        event_repository: "StrategyEventRepository",
        *,
        exchange: str,
        symbol: str,
        timeframe: str,
        start_date: datetime,
        end_date: datetime,
        since: datetime | None = None,
        event_limit: int = 1000,
    ) -> None:
        self.session_id = session_id
        self.event_repository = event_repository
        self.exchange = exchange
        self.symbol = symbol
        self.timeframe = timeframe
        self.start_date = start_date
        self.end_date = end_date
        self.since = since
        self.event_limit = event_limit

    async def load_timeline(self) -> dict[str, Any]:
        events = await self.event_repository.list_for_session(
            self.session_id, since=self.since, limit=self.event_limit
        )
        return {
            "session_id": self.session_id,
            "events": [_production_event_to_timeline(event) for event in events],
        }

    async def load_candles(self) -> list[list[float | int]]:
        # The core loader is synchronous and owns the shared ClickHouse client.
        # Running it in a worker thread preserves this source's async contract.
        from crypalgos_core.database import load_candles_from_clickhouse

        candles = await asyncio.to_thread(
            load_candles_from_clickhouse,
            exchange=self.exchange,
            symbol=self.symbol,
            start_date=self.start_date,
            end_date=self.end_date,
            timeframe=self.timeframe,
        )
        return [
            [int(row[0]), *(float(value) for value in row[1:])]
            for row in candles
        ]


def _production_event_to_timeline(event: Any) -> dict[str, Any]:
    """Match LiveService.get_session_timeline's event dict exactly."""
    return {
        "id": event.id,
        "type": event.event_type,
        "payload": event.payload,
        "created_at": event.created_at,
    }


def _archive_event_to_timeline(
    event: Mapping[str, Any], session_id: str, index: int
) -> dict[str, Any]:
    """Map a raw EngineEvent.to_dict() record into the durable timeline shape."""
    raw_payload = event.get("payload", {})
    payload = (
        dict(raw_payload) if isinstance(raw_payload, Mapping) else {"value": raw_payload}
    )
    base_fields = {
        key: value
        for key, value in event.items()
        if key not in {"id", "event_id", "type", "payload", "created_at"}
    }
    payload = {**base_fields, **payload}
    sequence = event.get("sequence_number", index)
    raw_created_at = event.get("created_at", event.get("timestamp"))
    created_at = _as_utc_datetime(raw_created_at)
    return {
        "id": event.get("id") or event.get("event_id") or f"{session_id}:{sequence}:{index}",
        "type": event.get("type", "UNKNOWN"),
        "payload": payload,
        "created_at": (
            created_at.isoformat()
            if created_at is not None
            else str(raw_created_at or "1970-01-01T00:00:00+00:00")
        ),
    }


def _as_utc_datetime(value: Any) -> datetime | None:
    """Parse EngineEvent/DB time values while accepting seconds through ns epochs."""
    if isinstance(value, datetime):
        return (
            value.replace(tzinfo=timezone.utc)
            if value.tzinfo is None
            else value.astimezone(timezone.utc)
        )
    if isinstance(value, (int, float)):
        seconds = float(value)
        while abs(seconds) >= 100_000_000_000:
            seconds /= 1000
        try:
            return datetime.fromtimestamp(seconds, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        stripped = value.strip()
        try:
            return _as_utc_datetime(float(stripped))
        except ValueError:
            try:
                parsed = datetime.fromisoformat(stripped.replace("Z", "+00:00"))
            except ValueError:
                return None
            return (
                parsed.replace(tzinfo=timezone.utc)
                if parsed.tzinfo is None
                else parsed.astimezone(timezone.utc)
            )
    return None
