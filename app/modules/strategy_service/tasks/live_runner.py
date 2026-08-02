import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from app.modules.strategy_service.execution.tick_sources import (
    DeltaMainnetTickSource,
    DeltaTestnetTickSource,
)
from app.modules.strategy_service.execution.trading_runtime import (
    RuntimeFactory,
    TradingRuntime,
)
from app.modules.strategy_service.models.live_trading_session_model import (
    LiveTradingSession,
    SessionEnvironment,
    SessionState,
)
from app.modules.strategy_service.services.session_workspace_archive import (
    SessionArchiveError,
)
from app.modules.strategy_service.utils.event_bus import EventBus

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL_SECS = 10
STOP_POLL_INTERVAL_SECS = 5


class LiveTradingRunner:
    """
    Celery-agnostic long-running engine loop for Live and Paper trading.

    Design principles:
    - EventBus is INJECTED — the runner never constructs infrastructure.
    - All config/credentials loaded from DB inside run() — no secrets in constructor args.
    - Can be driven by Celery, Supervisor, systemd, Kubernetes without changing this class.

    Only broker="delta" is supported — both LIVE and PAPER modes trade
    against real Delta market data (PAPER simulates fills over real prices,
    same as ExecutionRunner/Path B already does); there is no synthetic or
    other-exchange tick source yet (see plan Non-goals).
    """

    def __init__(self, session_id: str, event_bus: EventBus) -> None:
        self.session_id = session_id
        self.event_bus = event_bus
        self._session: Optional[LiveTradingSession] = None
        self._runtime: Optional[TradingRuntime] = None
        self._tick_source: Optional[Any] = None

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Main loop. Loads session config from DB, then runs until stopped."""
        completed_normally = False
        try:
            await self._bootstrap()
            if not await self._update_status(
                SessionState.RUNNING, started_at=datetime.now(timezone.utc)
            ):
                raise RuntimeError(
                    "Could not claim RUNNING status; another session may already be active."
                )
            await self._tick_source.start()

            last_heartbeat = 0.0
            while not await self._should_stop():
                bar_event = await self._tick_source.next_bar(
                    timeout=STOP_POLL_INTERVAL_SECS
                )
                if bar_event is not None:
                    try:
                        events = await self._runtime.tick(bar_event)
                        for event in events:
                            await self.event_bus.publish(event)
                    except SessionArchiveError:
                        # Continuing after an archive write failure would make
                        # Testnet replay non-deterministic, so fail the session.
                        logger.exception(
                            "[%s] Deterministic archive failed while processing bar at %s.",
                            self.session_id,
                            bar_event.timestamp,
                        )
                        raise
                    except Exception:
                        # A malformed candle, indicator recompute hiccup, or
                        # transient broker error affects only this bar.
                        logger.exception(
                            "[%s] Tick processing failed for bar at %s — "
                            "skipping this bar, session stays RUNNING.",
                            self.session_id,
                            bar_event.timestamp,
                        )

                now = asyncio.get_event_loop().time()
                if now - last_heartbeat >= HEARTBEAT_INTERVAL_SECS:
                    await self._update_heartbeat()
                    last_heartbeat = now
            completed_normally = True

        except Exception as e:
            logger.exception(f"LiveTradingRunner [{self.session_id}] crashed: {e}")
            await self._update_status(SessionState.ERROR, error_msg=str(e))
            raise
        finally:
            if self._tick_source is not None:
                await self._tick_source.stop()
            if self._runtime is not None:
                try:
                    await self._runtime.flush()
                except SessionArchiveError as e:
                    logger.exception(
                        "[%s] Deterministic archive failed while flushing.",
                        self.session_id,
                    )
                    await self._update_status(SessionState.ERROR, error_msg=str(e))
                    raise

        if completed_normally:
            await self._update_status(
                SessionState.STOPPED, stopped_at=datetime.now(timezone.utc)
            )

    # ------------------------------------------------------------------
    # Bootstrap — load all config from DB (no secrets passed via constructor)
    # ------------------------------------------------------------------

    async def _bootstrap(self) -> None:
        """
        Load session (with .strategy/.version eager-loaded), broker
        credentials, and build a TradingRuntime + tick source from them.
        """
        from app.db.connect_db import AsyncSessionLocal
        from app.modules.strategy_service.repositories.live_trading_session_repository import (
            LiveTradingSessionRepository,
        )
        from app.modules.user_service.services.credential_service import (
            credential_service,
        )

        async with AsyncSessionLocal() as session:
            repo = LiveTradingSessionRepository(session)
            self._session = await repo.get_by_id_with_relations(self.session_id)

        if not self._session:
            raise RuntimeError(f"LiveTradingSession {self.session_id} not found in DB")

        if self._session.broker != "delta":
            raise RuntimeError(
                f"Unsupported broker '{self._session.broker}' — only 'delta' is "
                "wired to a real market-data tick source today."
            )

        # The stored environment is the single source of truth for historical
        # warmup, broker endpoint, live feed, and replay. Both modes require
        # credentials because PAPER places real orders against Delta Testnet.
        is_testnet = self._session.environment == SessionEnvironment.TESTNET
        if not self._session.credential_id:
            raise RuntimeError(
                f"{self._session.mode} session has no credential_id — cannot trade."
            )

        broker_creds = await credential_service.get_decrypted_broker_credential(
            self._session.credential_id
        )
        if not broker_creds:
            raise RuntimeError(
                f"Broker credential {self._session.credential_id} not found or inactive."
            )
        if bool(broker_creds.is_testnet) != is_testnet:
            expected_environment = "Testnet" if is_testnet else "production"
            raise RuntimeError(
                f"Session environment requires a {expected_environment} Delta credential."
            )
        credentials = {
            "api_key": broker_creds.api_key,
            "api_secret": broker_creds.api_secret.get_secret_value(),
            "is_testnet": is_testnet,
        }

        self._runtime = await RuntimeFactory.build(self._session, credentials)

        self._tick_source = (
            DeltaTestnetTickSource(
                self._runtime.symbol,
                api_key=credentials["api_key"],
                api_secret=credentials["api_secret"],
            )
            if is_testnet
            else DeltaMainnetTickSource(self._runtime.symbol)
        )

        logger.info(
            f"LiveTradingRunner [{self.session_id}] bootstrapped. "
            f"mode={self._session.mode} broker={self._session.broker} "
            f"symbol={self._runtime.symbol} testnet={is_testnet}"
        )

    # ------------------------------------------------------------------
    # Stop signal
    # ------------------------------------------------------------------

    async def _should_stop(self) -> bool:
        """
        Check if the runner should exit.
        Fast path: Redis STOP_{session_id} key.
        Fallback: DB session status check.
        """
        # Fast path: Redis flag
        try:
            from app.celery_app import celery_app

            redis = celery_app.backend.client
            if redis.get(f"STOP_{self.session_id}"):
                logger.info(f"[{self.session_id}] Stop signal received via Redis.")
                redis.delete(f"STOP_{self.session_id}")
                return True
        except Exception:
            pass  # Redis unavailable — fall through to DB check

        # Fallback: DB session status
        try:
            from app.db.connect_db import AsyncSessionLocal
            from app.modules.strategy_service.repositories.live_trading_session_repository import (
                LiveTradingSessionRepository,
            )

            async with AsyncSessionLocal() as session:
                repo = LiveTradingSessionRepository(session)
                current = await repo.get_by_id(self.session_id)
                if current and current.status == SessionState.STOPPING:
                    return True
        except Exception as e:
            logger.warning(f"[{self.session_id}] DB stop-check failed: {e}")

        return False

    # ------------------------------------------------------------------
    # DB updates
    # ------------------------------------------------------------------

    async def _update_status(
        self,
        status: SessionState,
        error_msg: str | None = None,
        started_at: datetime | None = None,
        stopped_at: datetime | None = None,
    ) -> bool:
        try:
            from app.db.connect_db import AsyncSessionLocal
            from app.modules.strategy_service.repositories.live_trading_session_repository import (
                LiveTradingSessionRepository,
            )

            async with AsyncSessionLocal() as session:
                repo = LiveTradingSessionRepository(session)
                updated = await repo.update_status(
                    self.session_id,
                    status=status,
                    error_msg=error_msg,
                    started_at=started_at,
                    stopped_at=stopped_at,
                )
                if updated is None:
                    logger.error(
                        "[%s] Cannot update status to %s: session no longer exists.",
                        self.session_id,
                        status,
                    )
                    return False
                return True
        except Exception as e:
            logger.error(
                f"[{self.session_id}] Failed to update status to {status}: {e}"
            )
            return False

    async def _update_heartbeat(self) -> None:
        try:
            from app.db.connect_db import AsyncSessionLocal
            from app.modules.strategy_service.repositories.live_trading_session_repository import (
                LiveTradingSessionRepository,
            )

            async with AsyncSessionLocal() as session:
                repo = LiveTradingSessionRepository(session)
                await repo.update_heartbeat(
                    self.session_id,
                    heartbeat_at=datetime.now(timezone.utc),
                )
        except Exception as e:
            logger.warning(f"[{self.session_id}] Heartbeat update failed: {e}")
