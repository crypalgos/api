import asyncio
import logging
from datetime import datetime
from typing import Any

from crypalgos_core.optimization import (
    Constraint,
    Objective,
    OptimizationIR,
    ParameterDefinition,
)
from crypalgos_core.walkforward import (
    WalkForwardEngine,
    WalkForwardJob,
    build_full_report,
    validate_walk_forward_job,
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


async def _execute_walkforward_internal(
    run_id: str,
    strategy_id: str,
    start_date: datetime,
    end_date: datetime,
    initial_capital: float,
    window_config_json: dict,
    objective: str,
    strategy_version_id: str | None = None,
) -> dict[str, Any]:
    async with job_lifecycle_context(run_id, "Walk-forward task"):
        # Load and compile strategy
        async with AsyncSessionLocal() as session:
            strat_class = await load_and_compile_strategy(
                strategy_id, session, strategy_version_id=strategy_version_id
            )

        # Build optimization config from stored parameter_space
        parameter_space_json = window_config_json.get("parameter_space", [])
        constraints_json = window_config_json.get("constraints", [])
        opt_ir = OptimizationIR(
            parameters=[ParameterDefinition(**p) for p in parameter_space_json],
            constraints=[Constraint(**c) for c in constraints_json],
            objectives=[Objective(metric=objective, target="max")],
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
            leverage=next(
                iter(getattr(strat_class, "datasources", {}).values()), {}
            ).get(
                "leverage", 1
            ),  # type: ignore[call-overload]
        )
        validate_walk_forward_job(job)

        # Extract parameters from strategy class datasources if present
        symbols = []
        dataset_ids = []
        timeframe = "1m"
        leverage = 1
        if hasattr(strat_class, "datasources") and isinstance(
            strat_class.datasources, dict
        ):
            for ds_name, ds_info in strat_class.datasources.items():
                if isinstance(ds_info, dict):
                    sym = ds_info.get("symbol")
                    if sym:
                        symbols.append(sym)
                    tf = ds_info.get("timeframe")
                    if tf:
                        timeframe = tf
                    ds_id = ds_info.get("dataset_id")
                    if ds_id:
                        dataset_ids.append(ds_id)
                    lev = ds_info.get("leverage")
                    if lev is not None:
                        leverage = lev

        # Compute comprehensive run hash
        import hashlib
        import json

        hash_payload = {
            "strategy_version_id": strategy_version_id,
            "dataset_ids": sorted(dataset_ids),
            "symbols": sorted(symbols),
            "timeframe": timeframe,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "initial_capital": initial_capital,
            "commission": 0.0002,
            "slippage": 0.0002,
            "leverage": leverage,
            "window_config": window_config_json,
            "objective": objective,
        }
        hash_str = json.dumps(hash_payload, sort_keys=True, separators=(",", ":"))
        run_hash = hashlib.sha256(hash_str.encode("utf-8")).hexdigest()

        # Setup progress flusher
        flusher = AsyncProgressFlusher(run_id, "WALKFORWARD")
        flusher_task = asyncio.create_task(flusher.start_polling())

        wf_engine = WalkForwardEngine()
        try:
            result = await asyncio.to_thread(wf_engine.run, job, flusher.update)
        finally:
            flusher.stop()
            await flusher_task
        report = build_full_report(result)

        # S3-First storage uploads
        meta_payload = {
            "strategy_id": strategy_id,
            "run_id": run_id,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "initial_capital": initial_capital,
            "window_config": window_config_json,
            "objective": objective,
        }
        from dataclasses import asdict

        report_payload = {
            "report": asdict(report),
            "windows_count": len(result.windows),
        }

        # Measure size of S3 artifacts
        import msgpack

        artifact_size = len(msgpack.packb(report_payload, use_bin_type=True))

        metadata_key = (
            f"research/{strategy_id}/walkforwards/{run_id}/metadata.msgpack.zstd"
        )
        report_key = f"research/{strategy_id}/walkforwards/{run_id}/report.msgpack.zstd"

        await storage_service.upload_payload(metadata_key, meta_payload)
        await storage_service.upload_payload(report_key, report_payload)

        # Build database summary (extract validation metrics from the walkforward report's aggregate_metrics)
        summary_json = {
            "net_profit": float(report.aggregate_metrics.get("mean_net_profit", 0.0)),
            "total_return_pct": float(
                report.aggregate_metrics.get("mean_total_return_pct", 0.0)
            ),
            "sharpe_ratio": (
                float(report.aggregate_metrics.get("mean_sharpe_ratio", 0.0))
                if report.aggregate_metrics.get("mean_sharpe_ratio") is not None
                else None
            ),
            "sortino_ratio": (
                float(report.aggregate_metrics.get("mean_sortino_ratio", 0.0))
                if report.aggregate_metrics.get("mean_sortino_ratio") is not None
                else None
            ),
            "calmar_ratio": (
                float(report.aggregate_metrics.get("mean_calmar_ratio", 0.0))
                if report.aggregate_metrics.get("mean_calmar_ratio") is not None
                else None
            ),
            "max_drawdown_pct": float(
                report.aggregate_metrics.get("mean_max_drawdown", 0.0)
            ),
            "trade_count": int(report.aggregate_metrics.get("mean_trade_count", 0)),
            "windows_count": len(result.windows),
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

                # Register latest walkforward mapping
                latest = await session.get(StrategyLatestResults, strategy_id)
                if not latest:
                    latest = StrategyLatestResults(strategy_id=strategy_id)
                    session.add(latest)
                latest.latest_walkforward_id = run_id

        logger.info(
            f"Walk-forward run {run_id} completed with {len(result.windows)} windows."
        )
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
    strategy_version_id: str | None = None,
) -> dict[str, Any]:
    """Celery background task for walk-forward out-of-sample validation."""
    start_date = datetime.fromisoformat(start_date_iso)
    end_date = datetime.fromisoformat(end_date_iso)
    return asyncio.run(
        _execute_walkforward_internal(
            run_id=run_id,
            strategy_id=strategy_id,
            start_date=start_date,
            end_date=end_date,
            initial_capital=initial_capital,
            window_config_json=window_config_json,
            objective=objective,
            strategy_version_id=strategy_version_id,
        )
    )
