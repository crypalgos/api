import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.exceptions.exceptions import ResourceNotFoundException
from app.modules.strategy_service.models.live_trading_session_model import (
    LiveTradingSession,
)
from app.modules.strategy_service.repositories.live_trading_session_repository import (
    LiveTradingSessionRepository,
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
    ) -> tuple[int, Dict[str, Any]]:
        """
        Start a new Live or Paper trading session for a strategy.

        Guards:
        - Strategy ownership
        - No existing RUNNING/STARTING session (also enforced at DB level via partial unique index)
        - Mode must be LIVE or PAPER; broker must be supported
        """
        from app.modules.strategy_service.tasks import run_live_trading_task

        strategy = await self.strategy_repository.get_by_user_and_id(
            user_id, strategy_id
        )
        if not strategy or strategy.is_archived:
            raise ResourceNotFoundException("Strategy not found")

        mode = mode.upper()
        broker = broker.lower()

        if mode not in ("LIVE", "PAPER"):
            raise ValueError(f"Invalid mode '{mode}'. Must be LIVE or PAPER.")

        active_version = await self._ensure_active_version(strategy)

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

    @staticmethod
    def _serialize_session(session: LiveTradingSession) -> Dict[str, Any]:
        return {
            "id": session.id,
            "strategy_id": session.strategy_id,
            "version_id": session.version_id,
            "mode": session.mode,
            "broker": session.broker,
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
