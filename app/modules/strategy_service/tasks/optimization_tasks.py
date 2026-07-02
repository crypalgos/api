import asyncio
import logging
from datetime import datetime
from typing import Any

from crypalgos_core.optimization import (
    Constraint,
    Objective,
    OptimizationEngine,
    OptimizationIR,
    OptimizationJob,
    ParameterDefinition,
    build_leaderboard,
    validate_opt_ir,
)

from app.celery_app import celery_app
from app.db.connect_db import AsyncSessionLocal
from app.modules.strategy_service.models.research_run_model import (
    ResearchRun,
    StrategyLatestResults,
)
from app.modules.strategy_service.services.storage_service import storage_service
from app.modules.strategy_service.tasks.task_utils import (
    AsyncProgressFlusher,
    job_lifecycle_context,
    load_and_compile_strategy,
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
    strategy_version_id: str | None = None,
) -> dict[str, Any]:
    async with job_lifecycle_context(run_id, "Optimization task"):
        # Load and compile strategy
        async with AsyncSessionLocal() as session:
            strat_class = await load_and_compile_strategy(
                strategy_id, session, strategy_version_id=strategy_version_id
            )

        # Compute run hash for caching
        import hashlib
        import json

        hash_payload = {
            "strategy_version_id": strategy_version_id,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "initial_capital": initial_capital,
            "parameter_space": parameter_space_json,
            "constraints": constraints_json,
            "objective": objective,
            "search_type": search_type,
            "max_runs": max_runs,
        }
        hash_str = json.dumps(hash_payload, sort_keys=True)
        run_hash = hashlib.sha256(hash_str.encode("utf-8")).hexdigest()

        async with AsyncSessionLocal() as session:
            from sqlalchemy import select

            dup_stmt = (
                select(ResearchRun)
                .where(
                    ResearchRun.strategy_id == strategy_id,
                    ResearchRun.run_hash == run_hash,
                    ResearchRun.status == "COMPLETED",
                )
                .order_by(ResearchRun.completed_at.desc())
                .limit(1)
            )
            dup_res = await session.execute(dup_stmt)
            duplicate_run = dup_res.scalar_one_or_none()

            if duplicate_run:
                logger.info(
                    f"Reusing duplicate completed optimization run {duplicate_run.id} for hash {run_hash}"
                )
                async with session.begin():
                    run = await session.get(ResearchRun, run_id)
                    if run:
                        run.status = "COMPLETED"
                        run.completed_at = datetime.utcnow()
                        run.progress_percent = 100
                        run.metadata_s3_key = duplicate_run.metadata_s3_key
                        run.report_s3_key = duplicate_run.report_s3_key
                        run.summary_json = duplicate_run.summary_json
                        run.run_hash = run_hash
                        run.artifact_size_bytes = duplicate_run.artifact_size_bytes

                    latest = await session.get(StrategyLatestResults, strategy_id)
                    if not latest:
                        latest = StrategyLatestResults(strategy_id=strategy_id)
                        session.add(latest)
                    latest.latest_optimization_id = run_id
                return {
                    "success": True,
                    "run_id": run_id,
                    "total_results": (
                        duplicate_run.summary_json.get("total_results", 0)
                        if duplicate_run.summary_json
                        else 0
                    ),
                }

        # Build OptimizationIR
        params = [ParameterDefinition(**p) for p in parameter_space_json]
        constraints = [Constraint(**c) for c in (constraints_json or [])]
        opt_ir = OptimizationIR(
            parameters=params,
            constraints=constraints,
            objectives=[Objective(metric=objective, target="max")],
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
            symbol=next(iter(getattr(strat_class, "datasources", {}).values()), {}).get(
                "symbol", "BTCUSD"
            ),  # type: ignore[call-overload]
            opt_ir=opt_ir,
            initial_capital=initial_capital,
            leverage=next(
                iter(getattr(strat_class, "datasources", {}).values()), {}
            ).get(
                "leverage", 1
            ),  # type: ignore[call-overload]
        )

        # Setup progress flusher
        flusher = AsyncProgressFlusher(run_id, "OPTIMIZATION")
        flusher_task = asyncio.create_task(flusher.start_polling())

        # Run Engine in background thread
        engine_opt = OptimizationEngine()
        try:
            opt_run = await asyncio.to_thread(engine_opt.run, job, flusher.update)
        finally:
            flusher.stop()
            await flusher_task

        leaderboard = build_leaderboard(opt_run.results, top_n=50)
        best = opt_run.results[0] if opt_run.results else None

        # Build storage payloads
        meta_payload = {
            "strategy_id": strategy_id,
            "run_id": run_id,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "initial_capital": initial_capital,
            "parameter_space": parameter_space_json,
            "constraints": constraints_json,
            "search_type": search_type,
            "objective": objective,
            "max_runs": max_runs,
        }
        report_payload = {
            "leaderboard": leaderboard,
            "best_result": (
                {
                    "params": best.params,
                    "metrics": best.metrics,
                    "rank": best.rank,
                }
                if best
                else None
            ),
            "total_runs": len(opt_run.results),
        }

        # Measure size of S3 artifacts
        import msgpack

        artifact_size = len(msgpack.packb(report_payload, use_bin_type=True))

        metadata_key = (
            f"research/{strategy_id}/optimization/{run_id}/metadata.msgpack.zstd"
        )
        report_key = f"research/{strategy_id}/optimization/{run_id}/report.msgpack.zstd"

        await storage_service.upload_payload(metadata_key, meta_payload)
        await storage_service.upload_payload(report_key, report_payload)

        # Build database summary (take primary objectives from the best result if it exists)
        best_metrics = best.metrics if best else {}
        summary_json = {
            "net_profit": best_metrics.get("net_profit", 0.0),
            "total_return_pct": best_metrics.get("total_return_pct", 0.0),
            "sharpe_ratio": best_metrics.get("sharpe_ratio"),
            "sortino_ratio": best_metrics.get("sortino_ratio"),
            "calmar_ratio": best_metrics.get("calmar_ratio"),
            "max_drawdown_pct": best_metrics.get("max_drawdown_pct", 0.0),
            "trade_count": best_metrics.get("trade_count", 0),
            "total_results": len(opt_run.results),
        }

        # Update DB
        async with AsyncSessionLocal() as session:
            async with session.begin():
                run = await session.get(ResearchRun, run_id)
                if run:
                    run.status = "COMPLETED"
                    run.completed_at = datetime.utcnow()
                    run.progress_percent = 100
                    run.metadata_s3_key = metadata_key
                    run.report_s3_key = report_key
                    run.summary_json = summary_json
                    run.run_hash = run_hash
                    run.artifact_size_bytes = artifact_size

                # Register latest optimization mapping
                latest = await session.get(StrategyLatestResults, strategy_id)
                if not latest:
                    latest = StrategyLatestResults(strategy_id=strategy_id)
                    session.add(latest)
                latest.latest_optimization_id = run_id

        logger.info(
            f"Optimization run {run_id} completed with {len(opt_run.results)} results."
        )
        return {
            "success": True,
            "run_id": run_id,
            "total_results": len(opt_run.results),
        }


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
    strategy_version_id: str | None = None,
) -> dict[str, Any]:
    """Celery background task for parameter optimization using grid or random search."""
    start_date = datetime.fromisoformat(start_date_iso)
    end_date = datetime.fromisoformat(end_date_iso)
    return asyncio.run(
        _execute_optimization_internal(
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
            strategy_version_id=strategy_version_id,
        )
    )
