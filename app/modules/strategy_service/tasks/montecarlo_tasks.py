import asyncio
import logging
from datetime import datetime
from typing import Any

from crypalgos_core.montecarlo import (
    MonteCarloEngine,
    MonteCarloJob,
    MonteCarloMethod,
    build_montecarlo_report,
)

from app.celery_app import celery_app
from app.db.connect_db import AsyncSessionLocal
from app.modules.strategy_service.models.research_run_model import (
    ResearchRun,
    StrategyLatestResults,
)
from app.modules.strategy_service.services.storage_service import storage_service
from app.modules.strategy_service.tasks.task_utils import job_lifecycle_context

logger = logging.getLogger(__name__)


async def _execute_montecarlo_internal(
    run_id: str,
    strategy_id: str,
    source_backtest_id: str,
    simulation_count: int,
    method: str,
    random_seed: int | None,
    strategy_version_id: str | None = None,
) -> dict[str, Any]:
    async with job_lifecycle_context(run_id, "Monte Carlo task"):
        # Fetch the source backtest (read from its S3 report payload instead of database column)
        async with AsyncSessionLocal() as session:
            backtest_run = await session.get(ResearchRun, source_backtest_id)
            if not backtest_run:
                raise ValueError(f"Source backtest {source_backtest_id} not found.")
            backtest_report_key = backtest_run.report_s3_key
            if not backtest_report_key:
                raise ValueError(
                    f"Source backtest {source_backtest_id} report payload not found in storage."
                )

            backtest_payload = await storage_service.download_payload(
                backtest_report_key
            )

            trades = []
            workspace_key = backtest_run.artifact_manifest.get("workspace") if backtest_run.artifact_manifest else None
            if workspace_key:
                try:
                    import io
                    import pyarrow as pa
                    from app.modules.replay.utils.workspace_reader import WorkspaceReader
                    reader = WorkspaceReader(workspace_key)
                    trades_bytes = await reader.get_dataset_bytes("trades")
                    with pa.ipc.open_file(io.BytesIO(trades_bytes)) as reader_arrow:
                        table = reader_arrow.read_all()
                    trades = table.to_pylist()
                except Exception as e:
                    logger.error(f"Failed to read trades from workspace: {e}")

            if not trades:
                backtest_report = backtest_payload.get("charting")
                if backtest_report is None:
                    backtest_report = backtest_payload
                trades = backtest_report.get("trades", {}).get("recent_trades", [])

        mc_method = MonteCarloMethod(method)
        job = MonteCarloJob(
            simulation_count=simulation_count,
            method=mc_method,
            random_seed=random_seed,
            ruin_threshold_pct=0.20,
        )

        # Compute comprehensive run hash
        import hashlib
        import json

        hash_payload = {
            "strategy_version_id": strategy_version_id,
            "source_backtest_id": source_backtest_id,
            "simulation_count": simulation_count,
            "method": method,
            "random_seed": random_seed,
        }
        hash_str = json.dumps(hash_payload, sort_keys=True, separators=(",", ":"))
        run_hash = hashlib.sha256(hash_str.encode("utf-8")).hexdigest()

        class MockResearchResult:
            def __init__(self, trades):
                self.trades = trades

        if not trades:
            raise ValueError("Source backtest has no valid trades to run Monte Carlo.")

        research_result = MockResearchResult(trades)

        mc_engine = MonteCarloEngine()
        result = mc_engine.run(job, research_result=research_result)
        report = build_montecarlo_report(result)

        # S3-First storage uploads
        meta_payload = {
            "strategy_id": strategy_id,
            "run_id": run_id,
            "source_backtest_id": source_backtest_id,
            "simulation_count": simulation_count,
            "method": method,
            "random_seed": random_seed,
        }
        from dataclasses import asdict

        report_payload = {
            "report": asdict(report),
            "simulation_count": simulation_count,
        }

        # Measure size of S3 artifacts
        import msgpack

        artifact_size = len(msgpack.packb(report_payload, use_bin_type=True))

        metadata_key = (
            f"research/{strategy_id}/montecarlos/{run_id}/metadata.msgpack.zstd"
        )
        report_key = f"research/{strategy_id}/montecarlos/{run_id}/report.msgpack.zstd"

        await storage_service.upload_payload(metadata_key, meta_payload)
        await storage_service.upload_payload(report_key, report_payload)

        # Build database summary (extract percentile/metrics from Monte Carlo report)
        summary_json = {
            "median_drawdown": float(report.summary.get("median_drawdown", 0.0)),
            "worst_drawdown": float(report.summary.get("worst_drawdown", 0.0)),
            "probability_of_ruin": float(
                report.summary.get("probability_of_ruin", 0.0)
            ),
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

                # Register latest montecarlo mapping
                latest = await session.get(StrategyLatestResults, strategy_id)
                if not latest:
                    latest = StrategyLatestResults(strategy_id=strategy_id)
                    session.add(latest)
                latest.latest_montecarlo_id = run_id

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
    strategy_version_id: str | None = None,
) -> dict[str, Any]:
    """Celery background task for Monte Carlo statistical robustness analysis."""
    return asyncio.run(
        _execute_montecarlo_internal(
            run_id=run_id,
            strategy_id=strategy_id,
            source_backtest_id=source_backtest_id,
            simulation_count=simulation_count,
            method=method,
            random_seed=random_seed,
            strategy_version_id=strategy_version_id,
        )
    )
