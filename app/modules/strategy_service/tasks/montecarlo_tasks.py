import asyncio
from app.modules.strategy_service.schema.strategy_schema import JobStatus, RunType
from app.utils.artifact_paths import ArtifactPaths
from app.utils.time_utils import now_utc
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

            # The engine defaults to $10k if not told otherwise — but the
            # source backtest may have run with a different initial_capital
            # (stored in its metadata, meta_payload["initial_capital"] in
            # backtest_tasks.py). Using the wrong baseline here would put the
            # simulated fan and the real-equity overlay on different scales.
            initial_capital = 10000.0
            if backtest_run.metadata_s3_key:
                try:
                    backtest_meta = await storage_service.download_payload(backtest_run.metadata_s3_key)
                    initial_capital = float(backtest_meta.get("initial_capital", initial_capital))
                except Exception as e:
                    logger.error(f"Failed to read initial_capital from backtest metadata, defaulting to $10k: {e}")

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
                # MonteCarloEngine.run() reads research_result.portfolio_trades
                # (ADR-009 — Scenario Framework freeze; was .trade_pnls, a bare
                # float list). The trades read back off the workspace archive
                # already match PortfolioTradeRecord shape (CompletedTrade.to_dict()).
                self.portfolio_trades = trades

        if not trades:
            raise ValueError("Source backtest has no valid trades to run Monte Carlo.")

        research_result = MockResearchResult(trades)

        paths = ArtifactPaths(strategy_id=strategy_id, run_id=run_id, kind="montecarlos")

        mc_engine = MonteCarloEngine(initial_capital=initial_capital)
        result = mc_engine.run(job, research_result=research_result)

        # build_montecarlo_report writes the 4 chart datasets (sample_paths,
        # percentile_bands, simulation_summary, distributions) to
        # output_dir/datasets/montecarlo/*.arrow — without output_dir,
        # report.charts[*].dataset would point at files that never exist.
        # Write to a temp dir, then upload each to S3 at the same relative
        # path so replay/dashboard reads resolve correctly.
        import tempfile
        import os

        with tempfile.TemporaryDirectory() as tmp_dir:
            report = build_montecarlo_report(result, output_dir=tmp_dir)

            # real_equity.arrow — the actual backtest's real equity/drawdown
            # curve, for the bold "Real Strategy" overlay line. Lives here,
            # not in crypalgos_core: the engine has no concept of "the one
            # real run," only simulated pnl arrays. Same step-0-is-
            # initial_capital convention as the engine's own equity_curves,
            # so it's directly comparable on one chart.
            import pyarrow as pa

            real_equity: list[float] = [initial_capital]
            real_drawdown: list[float] = [0.0]
            running = initial_capital
            running_max = initial_capital
            for t in trades:
                running += float(t.get("net_pnl", 0.0))
                running_max = max(running_max, running)
                real_equity.append(running)
                real_drawdown.append((running_max - running) / max(running_max, 1e-6) * 100.0)
            real_equity_table = pa.Table.from_pydict({
                "step": list(range(len(real_equity))),
                "equity": real_equity,
                "drawdown": real_drawdown,
            })
            mc_datasets_dir = os.path.join(tmp_dir, "datasets", "montecarlo")
            os.makedirs(mc_datasets_dir, exist_ok=True)
            real_equity_path = os.path.join(mc_datasets_dir, "real_equity.arrow")
            with pa.OSFile(real_equity_path, "wb") as f:
                with pa.RecordBatchFileWriter(f, real_equity_table.schema) as writer:
                    writer.write_table(real_equity_table)

            if os.path.isdir(mc_datasets_dir):
                for filename in os.listdir(mc_datasets_dir):
                    dataset_name = filename.removesuffix(".arrow")
                    with open(os.path.join(mc_datasets_dir, filename), "rb") as f:
                        await storage_service.upload_raw_payload(
                            paths.montecarlo_dataset(dataset_name), f.read()
                        )

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

        metadata_key = paths.metadata
        report_key = paths.report

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
                    run.status=JobStatus.COMPLETED
                    run.completed_at = now_utc()
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
