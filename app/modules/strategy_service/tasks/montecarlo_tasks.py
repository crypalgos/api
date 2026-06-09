import asyncio
import logging
from datetime import datetime
from typing import Any

from crypalgos_core.montecarlo import (
    MonteCarloEngine, MonteCarloJob, MonteCarloMethod, build_montecarlo_report,
)

from app.celery_app import celery_app
from app.db.connect_db import AsyncSessionLocal
from app.modules.strategy_service.models.backtest_model import Backtest
from app.modules.strategy_service.models.montecarlo_model import MonteCarloRun
from app.modules.strategy_service.tasks.task_utils import job_lifecycle_context

logger = logging.getLogger(__name__)

async def _execute_montecarlo_internal(
    run_id: str,
    strategy_id: str,
    source_backtest_id: str,
    simulation_count: int,
    method: str,
    random_seed: int | None,
) -> dict[str, Any]:
    """Execute Monte Carlo simulation on existing backtest trades and persist results."""
    async with job_lifecycle_context(MonteCarloRun, run_id, "Monte Carlo task"):
        # Fetch the source backtest
        async with AsyncSessionLocal() as session:
            backtest = await session.get(Backtest, source_backtest_id)
            if not backtest:
                raise ValueError(f"Source backtest {source_backtest_id} not found.")
            backtest_report = backtest.charting_json

        mc_method = MonteCarloMethod(method)
        job = MonteCarloJob(
            simulation_count=simulation_count,
            method=mc_method,
            random_seed=random_seed,
        )

        mc_engine = MonteCarloEngine()
        result = mc_engine.run(job, backtest_report=backtest_report)
        report = build_montecarlo_report(result)

        # Update DB
        async with AsyncSessionLocal() as session:
            async with session.begin():
                run = await session.get(MonteCarloRun, run_id)
                run.status = "COMPLETED"
                run.completed_at = datetime.utcnow()
                run.summary_json = report
                run.progress_json = {
                    "completed_simulations": simulation_count,
                    "total_simulations": simulation_count
                }

        logger.info(f"Monte Carlo run {run_id} completed.")
        return {"success": True, "run_id": run_id}

@celery_app.task(name="app.modules.strategy_service.tasks.run_montecarlo_task")
def run_montecarlo_task(
    run_id: str,
    strategy_id: str,
    source_backtest_id: str,
    simulation_count: int,
    method: str,
    random_seed: int | None,
) -> dict[str, Any]:
    """Celery background task for Monte Carlo statistical robustness analysis."""
    return asyncio.run(_execute_montecarlo_internal(
        run_id=run_id,
        strategy_id=strategy_id,
        source_backtest_id=source_backtest_id,
        simulation_count=simulation_count,
        method=method,
        random_seed=random_seed,
    ))
