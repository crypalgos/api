import asyncio
import logging
from datetime import datetime
from typing import Any

from crypalgos_core.optimization import (
    OptimizationIR, ParameterDefinition, Objective, Constraint,
)
from crypalgos_core.walkforward import (
    WalkForwardEngine, WalkForwardJob, validate_walk_forward_job,
    build_full_report,
)

from app.celery_app import celery_app
from app.db.connect_db import AsyncSessionLocal
from app.modules.strategy_service.models.walkforward_model import WalkForwardRun
from app.modules.strategy_service.tasks.task_utils import (
    job_lifecycle_context, load_and_compile_strategy, AsyncProgressFlusher
)

logger = logging.getLogger(__name__)

async def _execute_walkforward_internal(
    run_id: str,
    strategy_id: str,
    start_date: datetime,
    end_date: datetime,
    initial_capital: float,
    window_config_json: dict,
    objective: str,
) -> dict[str, Any]:
    """Execute walk-forward validation engine and persist results."""
    async with job_lifecycle_context(WalkForwardRun, run_id, "Walk-forward task"):
        # Load and compile strategy
        async with AsyncSessionLocal() as session:
            strat_class = await load_and_compile_strategy(strategy_id, session)

        # Build optimization config from stored parameter_space
        parameter_space_json = window_config_json.get("parameter_space", [])
        constraints_json = window_config_json.get("constraints", [])
        opt_ir = OptimizationIR(
            parameters=[ParameterDefinition(**p) for p in parameter_space_json],
            constraints=[Constraint(**c) for c in constraints_json],
            objectives=[Objective(metric=objective, target="maximize")],
            search_type=window_config_json.get("search_type", "grid"),
            max_iterations=window_config_json.get("max_runs", 500),
        )

        job = WalkForwardJob(
            strategy_id=strategy_id,
            strategy_class=strat_class,
            optimization_config=opt_ir,
            train_window_months=window_config_json["train_period_months"],
            validation_window_months=window_config_json["test_period_months"],
            step_months=window_config_json["step_months"],
            data_start=start_date,
            data_end=end_date,
            initial_capital=initial_capital,
            leverage=next(iter(getattr(strat_class, "datasources", {}).values()), {}).get("leverage", 1),
        )
        validate_walk_forward_job(job)

        # Setup progress flusher
        flusher = AsyncProgressFlusher(WalkForwardRun, run_id)
        flusher_task = asyncio.create_task(flusher.start_polling())

        wf_engine = WalkForwardEngine()
        try:
            result = await asyncio.to_thread(wf_engine.run, job, flusher.update)
        finally:
            flusher.stop()
            await flusher_task
        report = build_full_report(result)

        # Update DB
        async with AsyncSessionLocal() as session:
            async with session.begin():
                run = await session.get(WalkForwardRun, run_id)
                run.status = "COMPLETED"
                run.completed_at = datetime.utcnow()
                run.summary_json = report
                run.progress_json = {
                    "completed_windows": len(result.windows),
                    "total_windows": len(result.windows)
                }

        logger.info(f"Walk-forward run {run_id} completed with {len(result.windows)} windows.")
        return {"success": True, "run_id": run_id, "windows": len(result.windows)}

@celery_app.task(name="app.modules.strategy_service.tasks.run_walkforward_task")
def run_walkforward_task(
    run_id: str,
    strategy_id: str,
    start_date_iso: str,
    end_date_iso: str,
    initial_capital: float,
    window_config_json: dict,
    objective: str,
) -> dict[str, Any]:
    """Celery background task for walk-forward out-of-sample validation."""
    start_date = datetime.fromisoformat(start_date_iso)
    end_date = datetime.fromisoformat(end_date_iso)
    return asyncio.run(_execute_walkforward_internal(
        run_id=run_id,
        strategy_id=strategy_id,
        start_date=start_date,
        end_date=end_date,
        initial_capital=initial_capital,
        window_config_json=window_config_json,
        objective=objective,
    ))
