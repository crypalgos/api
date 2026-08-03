import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.exceptions.exceptions import ResourceNotFoundException
from app.modules.strategy_service.models.live_trading_session_model import (
    LiveTradingSession,
    SessionEnvironment,
)
from app.modules.strategy_service.repositories.live_trading_session_repository import (
    LiveTradingSessionRepository,
)
from app.modules.strategy_service.repositories.strategy_event_repository import (
    StrategyEventRepository,
)

logger = logging.getLogger(__name__)


class LiveServiceMixin:
    """Mixin providing Live/Paper trading session management for StrategyService."""

    async def start_live_session(
        self,
        user_id: str,
        strategy_id: str,
        mode: str,
        broker: str,
        credential_id: Optional[str] = None,
    ) -> tuple[int, Dict[str, Any]]:
        """
        Start a new Live or Paper trading session for a strategy.

        Guards:
        - Strategy ownership
        - No existing RUNNING/STARTING session (also enforced at DB level via partial unique index)
        - Mode must be LIVE or PAPER; broker must be supported
        - mode=LIVE requires a credential_id the user actually owns
        """
        from app.modules.strategy_service.tasks import run_live_trading_task
        from app.modules.user_service.services.credential_service import (
            credential_service,
        )

        strategy = await self.strategy_repository.get_by_user_and_id(
            user_id, strategy_id
        )
        if not strategy or strategy.is_archived:
            raise ResourceNotFoundException("Strategy not found")

        mode = mode.upper()
        broker = broker.lower()

        if mode not in ("LIVE", "PAPER"):
            raise ValueError(f"Invalid mode '{mode}'. Must be LIVE or PAPER.")

        environment = (
            SessionEnvironment.TESTNET
            if mode == "PAPER"
            else SessionEnvironment.PRODUCTION
        )
        if not credential_id:
            raise ValueError(f"mode={mode} requires a credential_id.")

        owned_ids = {
            credential["id"]
            for credential in await credential_service.list_user_credentials(user_id)
        }
        if credential_id not in owned_ids:
            raise ResourceNotFoundException("Broker credential not found for this user.")

        credential = await credential_service.get_decrypted_broker_credential(
            credential_id
        )
        if not credential:
            raise ResourceNotFoundException("Broker credential is inactive or unavailable.")
        credential_exchange = str(
            getattr(credential.exchange, "value", credential.exchange)
        ).lower()
        if credential_exchange != "delta":
            raise ValueError("Live sessions require a Delta credential.")

        requires_testnet_credential = environment == SessionEnvironment.TESTNET
        if bool(credential.is_testnet) != requires_testnet_credential:
            expected_environment = "Testnet" if requires_testnet_credential else "production"
            other_mode = "LIVE" if mode == "PAPER" else "PAPER"
            raise ValueError(
                f"{mode} sessions require a {expected_environment} Delta credential; "
                f"use {other_mode} for the other Delta environment."
            )

        active_version = await self._ensure_active_version(strategy)
        from app.modules.strategy_service.execution.trading_runtime import (
            RuntimeFactory,
        )

        strategy_class = RuntimeFactory._load_strategy_class(active_version.compiled_code)
        symbol = RuntimeFactory._resolve_primary_symbol(strategy_class)
        timeframe = RuntimeFactory._resolve_primary_timeframe(strategy_class)
        exchange = str(getattr(strategy_class, "exchange", "delta")).lower()
        if exchange != "delta":
            raise ValueError(f"Unsupported live exchange '{exchange}'.")
        # "paper" is a UI execution-mode alias, not a market exchange.
        if broker == "paper":
            broker = exchange

        # Service-layer guard (DB partial unique index is the hard enforcement)
        live_repo = LiveTradingSessionRepository(self.strategy_repository.session)
        existing = await live_repo.get_active_session(strategy_id)
        if existing:
            raise ValueError(
                f"Strategy already has an active {existing.mode} session (id={existing.id}, status={existing.status}). "
                "Stop the existing session before starting a new one."
            )

        session = LiveTradingSession(
            strategy_id=strategy_id,
            version_id=active_version.id,
            mode=mode,
            broker=broker,
            exchange=exchange,
            environment=environment,
            symbol=symbol,
            timeframe=timeframe,
            credential_id=credential_id,
            status="STARTING",
        )

        live_repo.session.add(session)
        await live_repo.session.commit()
        await live_repo.session.refresh(session)

        # Enqueue Celery task — pass ONLY session_id (no secrets in queue)
        task = run_live_trading_task.delay(session_id=session.id)
        await live_repo.set_celery_task_id(session.id, task.id)

        logger.info(
            f"LiveSession started: id={session.id} mode={mode} broker={broker} task={task.id}"
        )

        return 202, {
            "session_id": session.id,
            "mode": session.mode,
            "exchange": session.exchange,
            "environment": session.environment,
            "symbol": session.symbol,
            "timeframe": session.timeframe,
            "broker": session.broker,
            "status": session.status,
            "celery_task_id": task.id,
            "message": f"{mode} trading session starting.",
        }

    async def stop_live_session(
        self, user_id: str, strategy_id: str, session_id: str
    ) -> tuple[int, Dict[str, Any]]:
        """
        Stop an active trading session.
        Sets Redis stop flag (fast path) + DB status = STOPPING (fallback).
        """
        strategy = await self.strategy_repository.get_by_user_and_id(
            user_id, strategy_id
        )
        if not strategy:
            raise ResourceNotFoundException("Strategy not found")

        live_repo = LiveTradingSessionRepository(self.strategy_repository.session)
        session = await live_repo.get_by_id(session_id)
        if not session or session.strategy_id != strategy_id:
            raise ResourceNotFoundException("Live trading session not found")

        session = await live_repo.reap_if_stale(session)
        if session.status in ("STOPPED", "ERROR"):
            return 200, {
                "session_id": session_id,
                "status": session.status,
                "message": "Session already stopped.",
            }

        # Fast path: Redis stop flag
        try:
            from app.celery_app import celery_app

            redis = celery_app.backend.client
            redis.set(f"STOP_{session_id}", "1", ex=300)
        except Exception as e:
            logger.warning(f"Could not set Redis stop flag: {e}")

        # Fallback: update DB status to STOPPING
        updated = await live_repo.update_status(session_id, "STOPPING")

        return 200, {
            "session_id": session_id,
            "status": updated.status if updated else "STOPPING",
            "message": "Stop signal sent. Session will halt shortly.",
        }

    async def get_live_session(
        self, user_id: str, strategy_id: str, session_id: str
    ) -> tuple[int, Dict[str, Any]]:
        """Get details of a single live trading session."""
        strategy = await self.strategy_repository.get_by_user_and_id(
            user_id, strategy_id
        )
        if not strategy:
            raise ResourceNotFoundException("Strategy not found")

        live_repo = LiveTradingSessionRepository(self.strategy_repository.session)
        session = await live_repo.get_by_id(session_id)
        if not session or session.strategy_id != strategy_id:
            raise ResourceNotFoundException("Live trading session not found")

        session = await live_repo.reap_if_stale(session)
        return 200, self._serialize_session(session)

    async def list_live_sessions(
        self, user_id: str, strategy_id: str
    ) -> tuple[int, List[Dict[str, Any]]]:
        """List all live trading sessions for a strategy."""
        strategy = await self.strategy_repository.get_by_user_and_id(
            user_id, strategy_id
        )
        if not strategy:
            raise ResourceNotFoundException("Strategy not found")

        live_repo = LiveTradingSessionRepository(self.strategy_repository.session)
        sessions = await live_repo.get_by_strategy(strategy_id)
        return 200, [self._serialize_session(s) for s in sessions]

    async def get_owned_session(
        self, user_id: str, session_id: str
    ) -> LiveTradingSession:
        """Resolves a LiveTradingSession by id alone (the flat /live-sessions/{id}/...
        routes, unlike the nested /strategies/{id}/live-sessions/{id} ones, don't
        have a strategy_id in the URL) and verifies the caller owns the strategy
        behind it — the same ownership check get_live_session() does, generalized
        for routes that only have a session_id."""
        live_repo = LiveTradingSessionRepository(self.strategy_repository.session)
        session = await live_repo.get_by_id(session_id)
        if not session:
            raise ResourceNotFoundException("Live trading session not found")

        strategy = await self.strategy_repository.get_by_user_and_id(
            user_id, session.strategy_id
        )
        if not strategy:
            raise ResourceNotFoundException("Live trading session not found")

        return session

    async def get_session_timeline(
        self,
        user_id: str,
        session_id: str,
        since: Optional[datetime] = None,
        limit: int = 2500,
    ) -> tuple[int, Dict[str, Any]]:
        """REST scrollback over strategy_events for one session — the same
        history WS /live-sessions/{id}/ws hydrates from on connect, and what
        a client falls back to on reconnect without depending solely on
        WS-delivered history."""
        session = await self.get_owned_session(user_id, session_id)
        if session.environment == SessionEnvironment.TESTNET:
            from app.modules.strategy_service.services.timeline_data_source import (
                TestnetTimelineDataSource,
            )

            timeline = await TestnetTimelineDataSource(
                session_id, session.artifact_manifest
            ).load_timeline(
                since=since,
                limit=limit,
            )
            return 200, timeline

        event_repo = StrategyEventRepository(self.strategy_repository.session)
        events = await event_repo.list_for_session(session_id, since=since, limit=limit)

        return 200, {
            "session_id": session_id,
            "events": [
                {
                    "id": e.id,
                    "type": e.event_type,
                    "payload": e.payload,
                    "created_at": e.created_at,
                }
                for e in events
            ],
        }

    async def get_session_replay(
        self, user_id: str, session_id: str
    ) -> tuple[int, Dict[str, Any]]:
        """Load a deterministic replay timeline from the session environment."""
        from datetime import timezone

        from app.modules.strategy_service.services.timeline_data_source import (
            ProductionTimelineDataSource,
            TestnetTimelineDataSource,
        )

        session = await self.get_owned_session(user_id, session_id)
        if session.environment == SessionEnvironment.TESTNET:
            source = TestnetTimelineDataSource(session.id, session.artifact_manifest)
        else:
            source = ProductionTimelineDataSource(
                session.id,
                StrategyEventRepository(self.strategy_repository.session),
                exchange=session.exchange,
                symbol=session.symbol,
                timeframe=session.timeframe,
                start_date=session.started_at or session.created_at,
                end_date=session.stopped_at or datetime.now(timezone.utc),
            )

        timeline = await source.load_timeline()
        candles = await source.load_candles()
        return 200, {
            "session_id": session.id,
            "mode": session.mode,
            "exchange": session.exchange,
            "environment": session.environment,
            "symbol": session.symbol,
            "timeframe": session.timeframe,
            "timeline": timeline,
            "candles": candles,
        }

    async def list_all_live_sessions(
        self,
        user_id: str,
        status: Optional[str] = None,
        mode: Optional[str] = None,
    ) -> tuple[int, List[Dict[str, Any]]]:
        """Cross-strategy session list for the fleet page — today's
        list_live_sessions() above is single-strategy-scoped only."""
        live_repo = LiveTradingSessionRepository(self.strategy_repository.session)
        sessions = await live_repo.list_all_for_user(user_id, status=status, mode=mode)
        return 200, [self._serialize_session(s) for s in sessions]

    @staticmethod
    def _serialize_session(session: LiveTradingSession) -> Dict[str, Any]:
        return {
            "id": session.id,
            "strategy_id": session.strategy_id,
            "version_id": session.version_id,
            "mode": session.mode,
            "broker": session.broker,
            "exchange": session.exchange,
            "environment": session.environment,
            "symbol": session.symbol,
            "timeframe": session.timeframe,
            "credential_id": session.credential_id,
            "status": session.status,
            "celery_task_id": session.celery_task_id,
            "error_msg": session.error_msg,
            "heartbeat_at": session.heartbeat_at,
            "last_processed_timestamp": session.last_processed_timestamp,
            "started_at": session.started_at,
            "stopped_at": session.stopped_at,
            "created_at": session.created_at,
            "updated_at": session.updated_at,
        }
