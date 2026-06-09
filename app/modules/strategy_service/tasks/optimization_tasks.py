import asyncio
import logging
from datetime import datetime
from typing import Any

from crypalgos_core.optimization import (
    OptimizationEngine, OptimizationJob, OptimizationIR,
    ParameterDefinition, Objective, Constraint,
    validate_opt_ir, build_leaderboard,
)

from app.celery_app import celery_app
from app.db.connect_db import AsyncSessionLocal
from app.modules.strategy_service.models.optimization_model import OptimizationRun
from app.modules.strategy_service.tasks.task_utils import (
    job_lifecycle_context, load_and_compile_strategy, AsyncProgressFlusher
)

logger = logging.getLogger(__name__)

async def _execute_optimization_internal(
    run_id: str,
    strategy_id: str,
    start_date: datetime,
    end_date: datetime,
    initial_capital: float,
    parameter_space_json: list,
    constraints_json: list,
    objective: str,
    search_type: str,
    max_runs: int,
) -> dict[str, Any]:
    """Execute optimization engine and persist results to the database."""
    async with job_lifecycle_context(OptimizationRun, run_id, "Optimization task"):
        # Load and compile strategy
        async with AsyncSessionLocal() as session:
            strat_class = await load_and_compile_strategy(strategy_id, session)

        # Build OptimizationIR
        params = [ParameterDefinition(**p) for p in parameter_space_json]
        constraints = [Constraint(**c) for c in (constraints_json or [])]
        opt_ir = OptimizationIR(
            parameters=params,
            constraints=constraints,
            objectives=[Objective(metric=objective, target="maximize")],
            search_type=search_type,
            max_iterations=max_runs,
        )
        validate_opt_ir(opt_ir)

        # Build Job
        job = OptimizationJob(
            strategy_class=strat_class,
            start_date=start_date,
            end_date=end_date,
            exchange=getattr(strat_class, "exchange", "delta"),
            symbol=next(iter(getattr(strat_class, "datasources", {}).values()), {}).get("symbol", "BTCUSD"),
            opt_ir=opt_ir,
            initial_capital=initial_capital,
            leverage=next(iter(getattr(strat_class, "datasources", {}).values()), {}).get("leverage", 1),
        )

        # Setup progress flusher
        flusher = AsyncProgressFlusher(OptimizationRun, run_id)
        flusher_task = asyncio.create_task(flusher.start_polling())

        # Run Engine in background thread so it doesn't block asyncio flusher
        engine_opt = OptimizationEngine()
        try:
            opt_run = await asyncio.to_thread(engine_opt.run, job, flusher.update)
        finally:
            flusher.stop()
            await flusher_task

        leaderboard = build_leaderboard(opt_run.results, top_n=50)
        best = opt_run.results[0] if opt_run.results else None

        # Update DB
        async with AsyncSessionLocal() as session:
            async with session.begin():
                run = await session.get(OptimizationRun, run_id)
                run.status = "COMPLETED"
                run.completed_at = datetime.utcnow()
                run.best_result_json = {"params": best.params, "metrics": best.metrics, "rank": best.rank} if best else None
                run.leaderboard_json = leaderboard
                run.progress_json = {"completed_runs": len(opt_run.results), "total_runs": max_runs}

        logger.info(f"Optimization run {run_id} completed with {len(opt_run.results)} results.")
        return {"success": True, "run_id": run_id, "total_results": len(opt_run.results)}

@celery_app.task(name="app.modules.strategy_service.tasks.run_optimization_task")
def run_optimization_task(
    run_id: str,
    strategy_id: str,
    start_date_iso: str,
    end_date_iso: str,
    initial_capital: float,
    parameter_space_json: list,
    constraints_json: list,
    objective: str,
    search_type: str,
    max_runs: int,
) -> dict[str, Any]:
    """Celery background task for parameter optimization using grid or random search."""
    start_date = datetime.fromisoformat(start_date_iso)
    end_date = datetime.fromisoformat(end_date_iso)
    return asyncio.run(_execute_optimization_internal(
        run_id=run_id,
        strategy_id=strategy_id,
        start_date=start_date,
        end_date=end_date,
        initial_capital=initial_capital,
        parameter_space_json=parameter_space_json,
        constraints_json=constraints_json,
        objective=objective,
        search_type=search_type,
        max_runs=max_runs,
    ))
