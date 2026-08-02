import asyncio
import json
import logging
import time
from typing import Iterable, List, Optional

from crypalgos_core.events.engine_events import EngineEvent

from app.db.connect_db import AsyncSessionLocal
from app.modules.strategy_service.execution.session_metrics import SessionMetrics
from app.modules.strategy_service.models.strategy_event_model import StrategyEvent
from app.modules.strategy_service.services.session_workspace_archive import (
    SessionArchiveError,
)

logger = logging.getLogger(__name__)

FLUSH_EVERY_N_EVENTS = 50
FLUSH_EVERY_SECS = 1.0


class EventPublisher:
    """The only component in the system allowed to write strategy_events or
    publish to Redis. TickEngine and TradingRuntime never call Redis/DB
    directly — everything routes through here, batched on the persist side.
    """

    def __init__(
        self,
        session_id: str,
        metrics: Optional[SessionMetrics] = None,
        archive: Optional[object] = None,
    ) -> None:
        self.session_id = session_id
        self.metrics = metrics
        self.archive = archive
        self._buffer: List[EngineEvent] = []
        self._last_flush = time.monotonic()
        self._lock = asyncio.Lock()

    async def persist(self, events: Iterable[EngineEvent]) -> None:
        events = list(events)
        if not events:
            return
        async with self._lock:
            self._buffer.extend(events)
            due = (
                len(self._buffer) >= FLUSH_EVERY_N_EVENTS
                or (time.monotonic() - self._last_flush) >= FLUSH_EVERY_SECS
            )
            if due:
                await self._flush_locked()

    async def flush(self) -> None:
        """Force a flush regardless of batch thresholds. Callers (TradingRuntime
        on session stop) must call this so the last partial batch isn't lost."""
        async with self._lock:
            await self._flush_locked()

    async def _flush_locked(self) -> None:
        if not self._buffer:
            self._last_flush = time.monotonic()
            return
        batch, self._buffer = self._buffer, []
        self._last_flush = time.monotonic()
        if self.archive is not None:
            try:
                self.archive.append_events(batch)
            except Exception as exc:
                logger.exception(
                    "Failed to archive %d events for session %s",
                    len(batch),
                    self.session_id,
                )
                raise SessionArchiveError(
                    f"Cannot preserve deterministic replay for session {self.session_id}"
                ) from exc
        try:
            async with AsyncSessionLocal() as session:
                for event in batch:
                    d = event.to_dict()
                    # d's own top-level fields (sequence_number, candle_index,
                    # parent_sequence, root_sequence, node_id, ...) are
                    # EngineEvent base fields, dropped by only ever storing
                    # d["payload"] -- they're what a trade-tree / decision
                    # replay needs to reconstruct causal chains later, and
                    # broadcast() already sends them (unmerged) over the live
                    # WS today. Folding them into the same flexible JSON
                    # column keeps the persisted shape a superset instead of
                    # a second, poorer schema. payload's own keys win on any
                    # collision (e.g. IndicatorSnapshotEvent redeclares its
                    # own `timestamp`) since they're more specific.
                    base_fields = {
                        k: v for k, v in d.items() if k not in ("type", "payload")
                    }
                    session.add(
                        StrategyEvent(
                            strategy_run_id=self.session_id,
                            session_id=self.session_id,
                            event_type=d["type"],
                            payload={**base_fields, **d["payload"]},
                        )
                    )
                await session.commit()
        except Exception:
            logger.exception(
                "Failed to persist %d events for session %s",
                len(batch),
                self.session_id,
            )

    def _get_redis(self):
        try:
            from app.celery_app import celery_app

            return celery_app.backend.client
        except Exception:
            logger.debug(
                "Redis unavailable; skipping live broadcast for %s", self.session_id
            )
            return None

    async def broadcast(self, events: Iterable[EngineEvent]) -> None:
        events = list(events)
        if not events:
            return
        redis = self._get_redis()
        if redis is None:
            return

        channel = f"live-session:{self.session_id}"
        for event in events:
            try:
                redis.publish(channel, json.dumps(event.to_dict(), default=str))
            except Exception:
                logger.exception("Failed to publish event to %s", channel)

    async def broadcast_raw(self, message: dict) -> None:
        """Publishes an arbitrary, non-EngineEvent dict straight to the live
        WS channel -- for lightweight, broadcast-only signals (e.g. a
        forming-bar price tick) that must never be persisted to
        strategy_events. Distinct from broadcast()'s typed-event path,
        which always goes through EngineEvent.to_dict().
        """
        redis = self._get_redis()
        if redis is None:
            return
        channel = f"live-session:{self.session_id}"
        try:
            redis.publish(channel, json.dumps(message, default=str))
        except Exception:
            logger.exception("Failed to publish raw message to %s", channel)

    def record_metrics(self, events: List[EngineEvent]) -> None:
        if self.metrics is None:
            return
        self.metrics.record_event_counts([type(e).__name__ for e in events])
