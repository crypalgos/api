import asyncio
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
from app.modules.strategy_service.tasks.task_utils import (
    AsyncProgressFlusher,
    compute_run_hash,
    extract_run_params,
    job_lifecycle_context,
    load_and_compile_strategy,
)

logger = logging.getLogger(__name__)


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
            logger.info(
                f"[DEV] Running backtest in-process for strategy {strategy_id} (version={strategy_version_id})"
            )

            from crypalgos_core import execute_strategy, ExecutionConfig

            flusher = AsyncProgressFlusher(backtest_id, "BACKTEST")
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

                report = {
                    "metrics": bundle.report.get("metrics", {}),
                    "market_data": [],
                    "trades": bundle.trades,
                    "runtime_events": bundle.runtime_events,
                    "decision_traces": bundle.decision_traces,
                    "execution_logs": bundle.execution_logs,
                    "orders": bundle.orders,
                    "portfolio_equity": bundle.equity_curve,
                    "portfolio_drawdown": bundle.drawdown_curve,
                    "indicator_snapshots": bundle.indicator_snapshots,
                    "dynamic_datasets": bundle.dynamic_datasets,
                    "report": bundle.report,
                }

            finally:
                flusher.stop()
                await flusher_task
        else:
            report = await asyncio.to_thread(  # type: ignore
                run_in_sandbox,
                strategy=strategy,
                exchange=exchange_name,
                symbol=symbols[0] if symbols else "BTCUSD",
                start_date=start_date,
                end_date=end_date,
                initial_capital=initial_capital,
                leverage=leverage,
            )

        from dataclasses import asdict
        from crypalgos_core.workspace.reporting_models import BacktestReport

        run_dict = report
        raw_metrics = run_dict.get("metrics", {})
        market_data_payload = run_dict.pop("market_data", [])
        trades_dict = run_dict.pop("trades", {})
        trades = (
            trades_dict.get("recent_trades", [])
            if isinstance(trades_dict, dict)
            else trades_dict
        )
        # Pop these immediately so they never leak into the report artifact
        runtime_events = run_dict.pop("runtime_events", [])
        decision_traces = run_dict.pop("decision_traces", [])
        execution_logs = run_dict.pop("execution_logs", [])
        orders = run_dict.pop("orders", [])
        portfolio_equity = run_dict.pop("portfolio_equity", [])
        portfolio_drawdown = run_dict.pop("portfolio_drawdown", [])
        indicator_snapshots = run_dict.pop("indicator_snapshots", [])
        dynamic_datasets = run_dict.pop("dynamic_datasets", {})

        # Enforce validation against BacktestReport dataclass
        report_data = run_dict.get("report") if "report" in run_dict else run_dict
        validated_report = BacktestReport(
            schema_version=report_data.get("schema_version", "4.2"),
            metrics=report_data.get("metrics", {}),
            correlations=report_data.get("correlations", {}),
            monthly=report_data.get("monthly", {}),
            datasets=report_data.get("datasets", {}),
            research_health=report_data.get("research_health", {}),
            quality_score=report_data.get("quality_score", 100),
            safety_recommendation=report_data.get("safety_recommendation", "APPROVED"),
            warnings=report_data.get("warnings", []),
            trade_audit=report_data.get("trade_audit", {}),
            trade_concentration=report_data.get("trade_concentration", {}),
            correlation_health=report_data.get("correlation_health", {}),
            fractional_kelly=report_data.get("fractional_kelly", {}),
            dataset_health=report_data.get("dataset_health", {}),
            distribution_warnings=report_data.get("distribution_warnings", []),
            anomaly_audit=report_data.get("anomaly_audit", {}),
            research_observability=report_data.get("research_observability", {}),
            equity_curve=report_data.get("equity_curve"),
        )
        validated_dict = asdict(validated_report)
        if "report" in run_dict:
            report_payload = {**run_dict, "report": validated_dict}
        else:
            report_payload = {**validated_dict}

        g_metrics = raw_metrics.get(
            "global", raw_metrics.get("global_metrics", raw_metrics)
        )

        # S3-First storage uploads
        meta_payload = {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "initial_capital": initial_capital,
            "strategy_id": strategy_id,
            "run_id": backtest_id,
            "market_data": market_data_payload,
        }

        dataset_payload = {
            "trades": trades,
            "orders": orders,
            "performance/global_equity_curve": portfolio_equity,
            "performance/global_drawdown_curve": portfolio_drawdown,
            "runtime_events": runtime_events,
            "decision_traces": decision_traces,
            "indicator_snapshots": indicator_snapshots,
            "execution_logs": execution_logs,
        }
        
        for ds_id, records in dynamic_datasets.items():
            dataset_payload[ds_id] = records

        # ── 1. Reconstruct DatasetRegistry ──
        from crypalgos_core.workspace.dataset_registry import DatasetRegistry
        from crypalgos_core.workspace.models import DatasetPayload, DatasetCategory

        registry = DatasetRegistry()
        for ds_id, records in dataset_payload.items():
            if ds_id in ("trades", "orders") or ds_id.startswith("execution/"): cat = DatasetCategory.EXECUTION
            elif ds_id.startswith("portfolio/"): cat = DatasetCategory.PORTFOLIO
            elif ds_id in ("runtime_events", "decision_traces", "indicator_snapshots", "execution_logs") or ds_id.startswith("decisions/"): cat = DatasetCategory.DECISIONS
            elif ds_id.startswith("analytics/"): cat = DatasetCategory.ANALYTICS
            else: cat = DatasetCategory.PORTFOLIO

            registry.register_payload(DatasetPayload(
                id=ds_id, category=cat, schema_version=1, records=records
            ))

        # ── 2. Build Workspace using Core Builder ──
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

        # Determine if strategy is multi-asset (default to False if uncertain, ReportBuilder handles it gracefully)
        is_multi = getattr(strat_class, "is_multi", False) if strat_class else False

        workspace_result = builder.build_workspace(
            report=validated_report,
            execution_context=execution_context,
            initial_capital=initial_capital,
            is_multi=is_multi,
            output_dir="",  # In MemoryStorage, this acts as the root
            archive_workspace=True,
            symbols_list=symbols or None
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

        # ── 4. Upload to S3 ──
        # 1. metadata.msgpack.zstd
        metadata_key = f"research/{strategy_id}/backtests/{backtest_id}/metadata.msgpack.zstd"
        await storage_service.upload_payload(metadata_key, meta_payload)

        import msgpack
        artifact_size = len(msgpack.packb(report_payload, use_bin_type=True))

        # 2. report.msgpack.zstd (Core generates report.json, but the API wants msgpack for the dashboard)
        report_key = f"research/{strategy_id}/backtests/{backtest_id}/report.msgpack.zstd"
        await storage_service.upload_payload(report_key, report_payload)

        # 3. workspace.tar.zstd (Generated directly by WorkspaceBuilder)
        workspace_key = f"research/{strategy_id}/backtests/{backtest_id}/workspace.tar.zstd"
        if archive_bytes:
            await storage_service.upload_raw_payload(workspace_key, archive_bytes)
            artifact_size += len(archive_bytes)
        
        # 4. runtime.arrow.zstd & decision.arrow.zstd
        # (These must still be extracted as separate S3 objects because the Arrow Window Reader expects them natively)
        # Typed envelope schema (artifact v2) — no first-row key inference
        from crypalgos_core.events.arrow_schemas import events_to_arrow_table

        if runtime_events:
            runtime_key = f"research/{strategy_id}/backtests/{backtest_id}/runtime.arrow.zstd"
            await storage_service.upload_arrow_payload(runtime_key, events_to_arrow_table(runtime_events))

        if decision_traces:
            decision_key = f"research/{strategy_id}/backtests/{backtest_id}/decision.arrow.zstd"
            await storage_service.upload_arrow_payload(decision_key, events_to_arrow_table(decision_traces))

        # 6. portfolio.arrow.zstd (Placeholder for now as it's not emitted separately)
        # Actually portfolio timeline is often mixed in dataset_registry as 'global_equity_curve'

        # Build clean summary json for database index
        total_trades = g_metrics.get("total_trades", g_metrics.get("trade_count", 0))
        net_profit = g_metrics.get("net_profit", 0.0)

        expectancy = g_metrics.get("expectancy")
        if expectancy is None:
            expectancy = (
                raw_metrics.get("distributions", {}).get("global", {}).get("expectancy")
            )

        average_trade = g_metrics.get("average_trade")
        if average_trade is None:
            average_trade = net_profit / total_trades if total_trades > 0 else 0.0

        if isinstance(symbols, dict):
            symbol_str = ", ".join(symbols.keys())
        elif isinstance(symbols, list):
            symbol_str = ", ".join(symbols)
        else:
            symbol_str = str(symbols) if symbols else ""

        # Extract and downsample equity curve for preview
        global_ref = run_dict.get("report", {}).get("equity_curve")
        equity_preview = []
        if global_ref and isinstance(global_ref, dict):
            global_equity_dataset_id = global_ref.get("dataset_id")
            if global_equity_dataset_id and global_equity_dataset_id in dataset_payload:
                full_equity_curve = dataset_payload[global_equity_dataset_id]
                try:
                    def _downsample(curve: list, threshold: int = 100) -> list:
                        if not curve or len(curve) <= threshold:
                            return curve
                        step = len(curve) / threshold
                        return [curve[int(i * step)] for i in range(threshold)]

                    equity_preview = _downsample(full_equity_curve, threshold=100)
                except Exception as e:
                    logger.error(f"Failed to downsample equity curve for preview: {e}")

        summary_json = {
            "net_profit": net_profit,
            "total_return_pct": g_metrics.get("total_return_pct", 0.0),
            "sharpe_ratio": g_metrics.get("sharpe_ratio"),
            "sortino_ratio": g_metrics.get("sortino_ratio"),
            "calmar_ratio": g_metrics.get("calmar_ratio"),
            "max_drawdown_pct": g_metrics.get("max_drawdown_pct", 0.0),
            "trade_count": total_trades,
            "win_rate": g_metrics.get("win_rate", 0.0),
            "expectancy": expectancy,
            "average_trade": average_trade,
            "exchange": exchange_name,
            "symbol": symbol_str,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "initial_capital": initial_capital,
            "leverage": leverage,
            "equity_preview": equity_preview,
        }

        # Update DB with results
        async with AsyncSessionLocal() as session:
            async with session.begin():
                run = await session.get(ResearchRun, backtest_id)
                if run:
                    run.status = "COMPLETED"
                    run.completed_at = datetime.utcnow()
                    run.progress_percent = 100

                    artifact_manifest = {
                        "metadata": metadata_key,
                        "report": report_key,
                        "workspace": workspace_key,
                    }
                    if runtime_events:
                        artifact_manifest["runtime"] = runtime_key
                    if decision_traces:
                        artifact_manifest["decision"] = decision_key

                    run.artifact_manifest = artifact_manifest

                    run.summary_json = summary_json
                    run.run_hash = run_hash
                    run.artifact_size_bytes = artifact_size

                # Register/update latest backtest mapping
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
