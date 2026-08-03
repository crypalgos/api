import os

from celery import Celery
from celery.schedules import crontab
from celery.signals import worker_ready

# Redis endpoint defaults to localhost for host development, can be configured via environment
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "crypalgos_api",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["app.modules.strategy_service.tasks"],
)


@worker_ready.connect
def _recover_orphaned_live_session_workspaces(**kwargs) -> None:
    """Fires once per worker boot, after the worker is fully up. Reconciles
    any live-session workspace left on local disk by a crash/deploy that
    skipped the normal close()-on-stop archive path. See
    live_session_recovery.py for the full reasoning."""
    from app.modules.strategy_service.tasks.live_session_recovery import (
        run_recovery_sync,
    )

    run_recovery_sync(**kwargs)

# Celery performance and serialization configurations
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    result_expires=3600,  # expire results in 1 hour
    beat_schedule={
        "cleanup-temporary-runs-daily": {
            "task": "app.modules.strategy_service.tasks.cleanup_temporary_runs",
            "schedule": crontab(hour=3, minute=0),  # 03:00 UTC daily
        },
    },
)
