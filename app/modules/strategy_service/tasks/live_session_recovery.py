"""Startup recovery for live-session workspaces that were never archived.

A worker that dies mid-session (crash, OOM, forced deploy) never reaches
LiveTradingRunner's normal finally-block flush(), so its
candles.parquet / strategy_events.msgpack / session.json sit on local disk
forever -- nothing else in the codebase ever revisits them. Run once per
worker boot: reconcile every local session directory against its DB row,
archive (upload -> verify -> delete, via SessionWorkspaceArchive.close())
anything whose session has actually ended, and leave anything genuinely
still RUNNING untouched.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path

from app.config.settings import settings
from app.modules.strategy_service.services.session_workspace_archive import (
    SessionWorkspaceArchive,
)

logger = logging.getLogger(__name__)

_TERMINAL_STATES = ("STOPPED", "ERROR")


def _register_all_models() -> None:
    """SQLAlchemy resolves every string-based relationship() target across
    the *whole* declarative graph the first time any mapper gets configured
    -- reap_if_stale() touching LiveTradingSession.credential/.strategy/etc.
    triggers that resolution, so every model those relationships (transitively)
    reference must already be imported, not just the ones this file directly
    touches. Same reason alembic/env.py imports this exact set -- kept in
    sync with it manually, since there's no single shared "all models"
    module in this codebase yet."""
    import app.modules.strategy_service.models.live_trading_session_model  # noqa: F401
    import app.modules.strategy_service.models.research_note_model  # noqa: F401
    import app.modules.strategy_service.models.research_run_model  # noqa: F401
    import app.modules.strategy_service.models.strategy_event_model  # noqa: F401
    import app.modules.strategy_service.models.strategy_model  # noqa: F401
    import app.modules.strategy_service.models.strategy_version_model  # noqa: F401
    import app.modules.user_service.models.contact_model  # noqa: F401
    import app.modules.user_service.models.credential_model  # noqa: F401
    import app.modules.user_service.models.session_model  # noqa: F401
    import app.modules.user_service.models.user_model  # noqa: F401
    import app.modules.user_service.models.waitlist_model  # noqa: F401


async def _recover_one(session_id: str) -> None:
    from app.db.connect_db import AsyncSessionLocal
    from app.modules.strategy_service.repositories.live_trading_session_repository import (
        LiveTradingSessionRepository,
    )

    _register_all_models()

    async with AsyncSessionLocal() as db_session:
        repo = LiveTradingSessionRepository(db_session)
        live_session = await repo.get_by_id(session_id)

        if live_session is None:
            # No matching row -- don't guess at a strategy_id to upload
            # under. Leave it on disk and flag it; this shouldn't happen
            # outside manual DB edits or a data-integrity issue.
            logger.warning(
                "Orphaned workspace %s has no matching live_trading_sessions "
                "row -- left on local disk for manual review.",
                session_id,
            )
            return

        if live_session.artifact_manifest is not None:
            # DB says this was already archived; a local copy surviving that
            # is redundant, not authoritative -- drop it.
            shutil.rmtree(
                SessionWorkspaceArchive._session_dir(session_id), ignore_errors=True
            )
            return

        live_session = await repo.reap_if_stale(live_session)
        if live_session.status not in _TERMINAL_STATES:
            # Fresh heartbeat -- an actively running session, not an orphan.
            return

        archive = SessionWorkspaceArchive(live_session.strategy_id, session_id)
        manifest = await archive.close()
        if manifest is not None:
            await repo.update_artifact_manifest(session_id, manifest)
            logger.info("Startup recovery archived orphaned session %s.", session_id)
        else:
            logger.warning(
                "Startup recovery could not archive session %s -- will retry "
                "on the next worker boot.",
                session_id,
            )


async def recover_orphaned_live_session_workspaces() -> None:
    root = Path(
        getattr(settings, "live_session_workspace_dir", "workspaces/live-sessions")
    )
    if not root.exists():
        return

    session_ids = [entry.name for entry in root.iterdir() if entry.is_dir()]
    if not session_ids:
        return

    logger.info(
        "Startup recovery: found %d local live-session workspace(s) to reconcile.",
        len(session_ids),
    )
    for session_id in session_ids:
        try:
            await _recover_one(session_id)
        except Exception:
            logger.exception(
                "Startup recovery failed for session %s -- left untouched "
                "for the next attempt.",
                session_id,
            )


def run_recovery_sync(**_kwargs) -> None:
    """Celery `worker_ready` signal handler entry point (sync context) --
    extra kwargs accepted because Celery signals pass a `sender` and other
    positional/keyword args this handler doesn't need."""
    try:
        asyncio.run(recover_orphaned_live_session_workspaces())
    except Exception:
        logger.exception("Live-session workspace recovery sweep failed.")
