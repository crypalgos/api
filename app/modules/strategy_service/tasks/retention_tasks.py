import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.celery_app import celery_app
from app.config.settings import settings
from app.db.connect_db import AsyncSessionLocal
from app.modules.strategy_service.models.research_run_model import ResearchRun
from app.modules.strategy_service.models.strategy_version_model import StrategyVersion
from app.modules.strategy_service.services.storage_service import storage_service

logger = logging.getLogger(__name__)


async def _cleanup_temporary_runs_async() -> dict:
    """Delete unpinned Analyse-tab temporary runs older than the retention
    window, along with their S3 artifacts and their still-unpromoted
    StrategyVersion snapshot -- pinned (is_favorite=True) runs are never
    touched, and a run that was Save()d is no longer is_temporary, so this
    can never delete a promoted result.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(
        days=settings.temporary_run_retention_days
    )
    deleted = 0

    async with AsyncSessionLocal() as session:
        stmt = select(ResearchRun).where(
            ResearchRun.is_temporary == True,  # noqa: E712
            ResearchRun.is_favorite == False,  # noqa: E712
            ResearchRun.created_at < cutoff,
        )
        result = await session.execute(stmt)
        runs = list(result.scalars().all())

        for run in runs:
            if run.artifact_manifest:
                for s3_key in run.artifact_manifest.values():
                    if s3_key:
                        await storage_service.delete_payload(s3_key)

            if run.strategy_version_id:
                version = await session.get(StrategyVersion, run.strategy_version_id)
                if version and version.is_temporary:
                    await session.delete(version)

            await session.delete(run)
            deleted += 1

        await session.commit()

    logger.info(f"Retention cleanup: deleted {deleted} temporary run(s) older than {cutoff.isoformat()}")
    return {"deleted": deleted, "cutoff": cutoff.isoformat()}


@celery_app.task(
    name="app.modules.strategy_service.tasks.cleanup_temporary_runs"
)
def cleanup_temporary_runs() -> dict:
    """Daily beat task -- see _cleanup_temporary_runs_async()."""
    return asyncio.run(_cleanup_temporary_runs_async())
