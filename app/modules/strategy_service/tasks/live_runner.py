import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from app.modules.strategy_service.utils.event_bus import EventBus
from app.modules.strategy_service.utils.broker_factory import BrokerFactory

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
    """

    def __init__(self, session_id: str, event_bus: EventBus) -> None:
        self.session_id = session_id
        self.event_bus = event_bus
        self._broker = None
        self._session = None
        self._strategy_class = None

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Main loop. Loads session config from DB, then runs until stopped."""
        try:
            await self._bootstrap()
            await self._update_status("RUNNING", started_at=datetime.now(timezone.utc))

            last_heartbeat = 0.0
            while not await self._should_stop():
                events = await self._tick()
                for event in events:
                    await self.event_bus.publish(event)

                now = asyncio.get_event_loop().time()
                if now - last_heartbeat >= HEARTBEAT_INTERVAL_SECS:
                    await self._update_heartbeat()
                    last_heartbeat = now

                await asyncio.sleep(STOP_POLL_INTERVAL_SECS)

        except Exception as e:
            logger.exception(f"LiveTradingRunner [{self.session_id}] crashed: {e}")
            await self._update_status("ERROR", error_msg=str(e))
            raise
        else:
            await self._update_status("STOPPED", stopped_at=datetime.now(timezone.utc))

    # ------------------------------------------------------------------
    # Bootstrap — load all config from DB (no secrets passed via constructor)
    # ------------------------------------------------------------------

    async def _bootstrap(self) -> None:
        """
        Load session, strategy version, and broker credentials from DB.
        Build broker via BrokerFactory.
        """
        from app.db.connect_db import get_sync_session
        from app.modules.strategy_service.repositories.live_trading_session_repository import (
            LiveTradingSessionRepository,
        )
        from app.modules.user_service.services.credential_service import (
            credential_service,
        )

        async with get_sync_session() as session:
            repo = LiveTradingSessionRepository(session)
            self._session = await repo.get_by_id(self.session_id)

        if not self._session:
            raise RuntimeError(f"LiveTradingSession {self.session_id} not found in DB")

        # Load credentials from encrypted store
        try:
            credentials = await credential_service.get_broker_credentials(
                self._session.strategy.user_id,
                broker=self._session.broker,
            )
            api_key = credentials.get("api_key", "") if credentials else ""
            api_secret = credentials.get("api_secret", "") if credentials else ""
        except Exception:
            logger.warning(
                f"[{self.session_id}] Could not load broker credentials — using empty keys (PAPER mode safe)"
            )
            api_key, api_secret = "", ""

        self._broker = BrokerFactory.create(
            mode=self._session.mode,
            broker=self._session.broker,
            api_key=api_key,
            api_secret=api_secret,
        )
        logger.info(
            f"LiveTradingRunner [{self.session_id}] bootstrapped. "
            f"mode={self._session.mode} broker={self._session.broker}"
        )

    # ------------------------------------------------------------------
    # Engine tick
    # ------------------------------------------------------------------

    async def _tick(self) -> list[Any]:
        """
        Execute one strategy tick:
        1. Fetch latest candle(s) for the strategy's datasources
        2. Run strategy logic via compiled strategy class
        3. Collect and return emitted events

        Returns:
            List of engine events to publish to EventBus
        """
        # TODO: integrate crypalgos_core engine tick when live engine API is stable
        # Placeholder returns empty list — safe to deploy
        return []

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
            from app.db.connect_db import get_sync_session
            from app.modules.strategy_service.repositories.live_trading_session_repository import (
                LiveTradingSessionRepository,
            )

            async with get_sync_session() as session:
                repo = LiveTradingSessionRepository(session)
                current = await repo.get_by_id(self.session_id)
                if current and current.status == "STOPPING":
                    return True
        except Exception as e:
            logger.warning(f"[{self.session_id}] DB stop-check failed: {e}")

        return False

    # ------------------------------------------------------------------
    # DB updates
    # ------------------------------------------------------------------

    async def _update_status(
        self,
        status: str,
        error_msg: str | None = None,
        started_at: datetime | None = None,
        stopped_at: datetime | None = None,
    ) -> None:
        try:
            from app.db.connect_db import get_sync_session
            from app.modules.strategy_service.repositories.live_trading_session_repository import (
                LiveTradingSessionRepository,
            )

            async with get_sync_session() as session:
                repo = LiveTradingSessionRepository(session)
                await repo.update_status(
                    self.session_id,
                    status=status,
                    error_msg=error_msg,
                    started_at=started_at,
                    stopped_at=stopped_at,
                )
        except Exception as e:
            logger.error(
                f"[{self.session_id}] Failed to update status to {status}: {e}"
            )

    async def _update_heartbeat(self) -> None:
        try:
            from app.db.connect_db import get_sync_session
            from app.modules.strategy_service.repositories.live_trading_session_repository import (
                LiveTradingSessionRepository,
            )

            async with get_sync_session() as session:
                repo = LiveTradingSessionRepository(session)
                await repo.update_heartbeat(
                    self.session_id,
                    heartbeat_at=datetime.now(timezone.utc),
                )
        except Exception as e:
            logger.warning(f"[{self.session_id}] Heartbeat update failed: {e}")
