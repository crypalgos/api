import asyncio
from app.modules.strategy_service.schema.strategy_schema import JobStatus, RunType
import logging
from datetime import datetime
from typing import Any

from app.celery_app import celery_app
from app.config.settings import settings
from app.db.connect_db import AsyncSessionLocal
from app.modules.strategy_service.models.research_run_model import (
    ResearchRun,
    StrategyLatestResults,
)
from app.modules.strategy_service.models.strategy_model import Strategy
from app.modules.strategy_service.services.storage_service import storage_service
from app.modules.strategy_service.tasks.sandbox import run_in_sandbox
from app.modules.strategy_service.schemas.run_summary_schema import RunSummary
from app.modules.strategy_service.tasks.task_utils import (
    AsyncProgressFlusher,
    compute_run_hash,
    extract_run_params,
    job_lifecycle_context,
    load_and_compile_strategy,
)
from app.utils.artifact_paths import ArtifactPaths
from app.utils.time_utils import now_utc

logger = logging.getLogger(__name__)


def _downsample(curve: list, threshold: int = 100) -> list:
    if not curve or len(curve) <= threshold:
        return curve
    step = len(curve) / threshold
    return [curve[int(i * step)] for i in range(threshold)]


async def _execute_backtest_internal(
    backtest_id: str,
    strategy_id: str,
    start_date: datetime,
    end_date: datetime,
    initial_capital: float,
    strategy_version_id: str | None = None,
) -> dict[str, Any]:
    async with job_lifecycle_context(backtest_id, "Backtest task"):
        # Load strategy and compile class first
        async with AsyncSessionLocal() as session:
            strat_class = await load_and_compile_strategy(
                strategy_id, session, strategy_version_id=strategy_version_id
            )
            if strategy_version_id:
                from app.modules.strategy_service.models.strategy_version_model import (
                    StrategyVersion,
                )

                strategy = await session.get(StrategyVersion, strategy_version_id)
            else:
                strategy = await session.get(Strategy, strategy_id)

        # Execution inputs come from the strategy graph — never defaulted
        run_params = extract_run_params(strat_class)
        symbols = run_params.symbols
        leverage = run_params.leverage
        exchange_name = run_params.exchange_name

        from crypalgos_data.exchanges.config import EXCHANGE_REGISTRY

        exchange_cls = EXCHANGE_REGISTRY[exchange_name]

        commission = 0.0002  # Default maker fee
        slippage = 0.0002

        run_hash = compute_run_hash(
            strategy_version_id=strategy_version_id,
            compiled_code=getattr(strategy, "compiled_code", None),
            params=run_params,
            start_date=start_date,
            end_date=end_date,
            initial_capital=initial_capital,
            commission=commission,
            slippage=slippage,
        )

        USE_SANDBOX = settings.sandbox_enabled

        if not USE_SANDBOX:
            # A9: in-process execution runs user strategy code inside the worker
            # with full credentials — acceptable single-tenant/dev only.
            logger.warning(
                f"SANDBOX DISABLED: executing strategy {strategy_id} in-process "
                f"(version={strategy_version_id}). Enable sandbox_enabled before "
                "accepting external strategies."
            )

            from crypalgos_core import execute_strategy, ExecutionConfig

            flusher = AsyncProgressFlusher(backtest_id, RunType.BACKTEST)
            flusher_task = asyncio.create_task(flusher.start_polling())

            try:
                config = ExecutionConfig(
                    strategy_class=strat_class,
                    start_date=start_date,
                    end_date=end_date,
                    initial_capital=initial_capital,
                    leverage=leverage,
                    exchange_config=exchange_cls(),
                    slippage_rate=slippage,
                    progress_callback=flusher.update,
                )
                bundle = await asyncio.to_thread(execute_strategy, config)

                # The one process-boundary mapping — owned by core, never hand-built
                report = bundle.to_payload_dict()
                registry = bundle.datasets

            finally:
                flusher.stop()
                await flusher_task
        else:
            report = await asyncio.to_thread(  # type: ignore
                run_in_sandbox,
                strategy=strategy,
                exchange=exchange_name,
                symbol=symbols[0] if symbols else "",
                start_date=start_date,
                end_date=end_date,
                initial_capital=initial_capital,
                leverage=leverage,
            )
            # Inverse of WorkspaceBundle.to_payload_dict() across the JSON boundary
            from crypalgos_core.workspace.dataset_registry import DatasetRegistry

            registry = DatasetRegistry.from_payload_dict(report)

        from dataclasses import asdict
        from crypalgos_core.workspace.reporting_models import BacktestReport

        raw_metrics = report.get("metrics", {})
        runtime_events = report.get("runtime_events", [])
        decision_traces = report.get("decision_traces", [])

        # Strict validation — a malformed report is an error, never silently APPROVED
        validated_report = BacktestReport.from_dict(report.get("report", {}))
        validated_dict = asdict(validated_report)

        # Slim report artifact: bulky datasets live in the workspace, not here
        _BULK_KEYS = {
            "market_data", "trades", "orders", "runtime_events", "decision_traces",
            "execution_logs", "indicator_snapshots", "portfolio_equity",
            "portfolio_drawdown", "candles", "dynamic_datasets", "dataset_categories",
        }
        report_payload = {k: v for k, v in report.items() if k not in _BULK_KEYS}
        report_payload["report"] = validated_dict

        # S3-First storage uploads
        meta_payload = {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "initial_capital": initial_capital,
            "strategy_id": strategy_id,
            "run_id": backtest_id,
            "market_data": report.get("market_data", []),
        }

        # ── Build Workspace using Core Builder ──
        from crypalgos_core.workspace.storage import MemoryStorage
        from crypalgos_core.workspace.workspace_builder import WorkspaceBuilder
        
        storage = MemoryStorage()
        builder = WorkspaceBuilder.create(registry, storage)
        
        execution_context = {
            "strategy_id": strategy_id,
            "run_id": backtest_id,
            "workspace_id": backtest_id,
            "execution_mode": "BACKTEST",
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "initial_capital": initial_capital,
            "duration": int((end_date - start_date).total_seconds())
        }

        is_multi = bool(report.get("is_multi", len(symbols) > 1))
        symbols_list = report.get("symbols_list") or symbols or None

        workspace_result = builder.build_workspace(
            report=validated_report,
            execution_context=execution_context,
            initial_capital=initial_capital,
            is_multi=is_multi,
            output_dir="",  # In MemoryStorage, this acts as the root
            archive_workspace=True,
            symbols_list=symbols_list
        )

        manifest = workspace_result.get("manifest", {})
        archive_bytes = workspace_result.get("archive_bytes")

        # ── 3. Validate references (optional double check) ──
        from app.modules.strategy_service.tasks.task_utils import (
            enrich_dataset_references,
            extract_dataset_ids,
        )
        report_nested = report_payload.get("report", {})
        
        # Enrich references with manifest data
        generated_metas = {ds["dataset_id"]: ds for ds in manifest.get("datasets", [])}
        enrich_dataset_references(report_nested, generated_metas)

        referenced_ids = set()
        extract_dataset_ids(report_nested, referenced_ids)
        referenced_ids = {rid for rid in referenced_ids if rid}
        manifest_ids = set(generated_metas.keys())

        missing_ids = referenced_ids - manifest_ids
        if missing_ids:
            logger.warning(f"Workspace validation: Referenced dataset IDs {missing_ids} are missing from the manifest.")

        # ── 4. Upload to S3 (all keys via ArtifactPaths — never inline) ──
        paths = ArtifactPaths(strategy_id=strategy_id, run_id=backtest_id, kind="backtests")

        await storage_service.upload_payload(paths.metadata, meta_payload)

        import msgpack
        artifact_size = len(msgpack.packb(report_payload, use_bin_type=True))

        # Split-artifact delivery (see report_split.py): behind a flag so
        # this is a no-op, zero-risk change until explicitly opted into. When
        # on, per-tab sections replace the single monolithic report blob
        # entirely for this run — cheaper to write (small msgpack, no zstd)
        # and cheaper to read (only the open tab's section gets fetched, via
        # the same /artifacts/{type} endpoint as the old monolithic report).
        report_section_keys: dict[str, str] = {}
        if settings.report_delivery_v2_enabled:
            from app.modules.strategy_service.services.report_split import (
                split_and_upload,
            )
            report_section_keys = await split_and_upload(paths, "BACKTEST", validated_dict)
        else:
            # report.msgpack.zstd (Core generates report.json, but the API wants msgpack for the dashboard)
            await storage_service.upload_payload(paths.report, report_payload)

        # workspace.tar.zstd (Generated directly by WorkspaceBuilder)
        if archive_bytes:
            await storage_service.upload_raw_payload(paths.workspace, archive_bytes)
            artifact_size += len(archive_bytes)

        # runtime.arrow.zstd & decision.arrow.zstd
        # (Separate S3 objects because the Arrow Window Reader expects them natively)
        # Typed envelope schema (artifact v2) — no first-row key inference
        from crypalgos_core.events.arrow_schemas import events_to_arrow_table

        if runtime_events:
            await storage_service.upload_arrow_payload(paths.runtime, events_to_arrow_table(runtime_events))

        if decision_traces:
            await storage_service.upload_arrow_payload(paths.decision, events_to_arrow_table(decision_traces))

        # Extract and downsample equity curve for the dashboard preview
        equity_preview = []
        global_ref = validated_dict.get("equity_curve")
        if isinstance(global_ref, dict) and global_ref.get("dataset_id"):
            curve_payload = registry.get_payload(global_ref["dataset_id"])
            if curve_payload and curve_payload.records:
                equity_preview = _downsample(curve_payload.records, threshold=100)

        summary = RunSummary.from_backtest_metrics(
            raw_metrics,
            params=run_params,
            start_date_iso=start_date.isoformat(),
            end_date_iso=end_date.isoformat(),
            initial_capital=initial_capital,
            equity_preview=equity_preview,
        )
        summary_json = summary.model_dump()

        # Update DB with results
        async with AsyncSessionLocal() as session:
            async with session.begin():
                run = await session.get(ResearchRun, backtest_id)
                if run:
                    run.status=JobStatus.COMPLETED
                    run.completed_at = now_utc()
                    run.progress_percent = 100

                    artifact_manifest = {
                        "metadata": paths.metadata,
                        "workspace": paths.workspace,
                    }
                    if report_section_keys:
                        artifact_manifest.update(report_section_keys)
                    else:
                        artifact_manifest["report"] = paths.report
                    if runtime_events:
                        artifact_manifest["runtime"] = paths.runtime
                    if decision_traces:
                        artifact_manifest["decision"] = paths.decision

                    run.artifact_manifest = artifact_manifest

                    run.summary_json = summary_json
                    run.run_hash = run_hash
                    run.artifact_size_bytes = artifact_size

                # Register/update latest backtest mapping -- skip for
                # Analyse-tab temporary runs, which must never hijack the
                # dashboard's "latest backtest" preview (save_run() sets
                # this explicitly once a temp run is promoted).
                if run and not run.is_temporary:
                    latest = await session.get(StrategyLatestResults, strategy_id)
                    if not latest:
                        latest = StrategyLatestResults(strategy_id=strategy_id)
                        session.add(latest)
                    latest.latest_backtest_id = backtest_id

        logger.info(
            f"Asynchronous Celery backtest run successfully completed and saved: {backtest_id}"
        )
        return {"success": True, "backtest_id": backtest_id, "summary": summary_json}


@celery_app.task(
    name="app.modules.strategy_service.tasks.run_asynchronous_backtest_task"
)
def run_asynchronous_backtest_task(
    backtest_id: str,
    strategy_id: str,
    start_date_iso: str,
    end_date_iso: str,
    initial_capital: float,
    strategy_version_id: str | None = None,
) -> dict[str, Any]:
    """Celery background task orchestrating quantitative backtest simulation."""
    start_date = datetime.fromisoformat(start_date_iso)
    end_date = datetime.fromisoformat(end_date_iso)
    return asyncio.run(
        _execute_backtest_internal(
            backtest_id=backtest_id,
            strategy_id=strategy_id,
            start_date=start_date,
            end_date=end_date,
            initial_capital=initial_capital,
            strategy_version_id=strategy_version_id,
        )
    )
