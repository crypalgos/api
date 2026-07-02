import asyncio
import logging
from datetime import datetime
from typing import Any

from crypalgos_data.exchanges.config import EXCHANGE_REGISTRY
from crypalgos_core.engine.simulator import EngineSimulator

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

        # Extract parameters from strategy class datasources if present
        symbols = []
        dataset_ids = []
        timeframe = "1m"
        leverage = 1
        exchange_name = "delta"
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
                    exc = ds_info.get("exchange") or ds_info.get("broker")
                    if exc:
                        exchange_name = exc

        commission = 0.0002  # Default maker fee
        slippage = 0.0002

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
            "commission": commission,
            "slippage": slippage,
            "leverage": leverage,
            "exchange": exchange_name,
        }
        hash_str = json.dumps(hash_payload, sort_keys=True, separators=(",", ":"))
        run_hash = hashlib.sha256(hash_str.encode("utf-8")).hexdigest()

        USE_SANDBOX = settings.sandbox_enabled

        if not USE_SANDBOX:
            logger.info(
                f"[DEV] Running backtest in-process for strategy {strategy_id} (version={strategy_version_id})"
            )

            simulator = EngineSimulator(
                exchange_config=EXCHANGE_REGISTRY.get(
                    exchange_name, EXCHANGE_REGISTRY["delta"]
                )(),
                initial_capital=initial_capital,
                leverage=leverage,
                slippage_rate=slippage,
            )

            # Setup progress flusher
            flusher = AsyncProgressFlusher(backtest_id, "BACKTEST")
            flusher_task = asyncio.create_task(flusher.start_polling())

            try:
                report = await asyncio.to_thread(
                    simulator.run,
                    strategy_class=strat_class,
                    start_date=start_date,
                    end_date=end_date,
                    progress_callback=flusher.update,
                )
            finally:
                flusher.stop()
                await flusher_task
        else:
            report = await asyncio.to_thread(  # type: ignore
                run_in_sandbox,
                strategy=strategy,
                start_date=start_date,
                end_date=end_date,
                initial_capital=initial_capital,
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
            report_payload = validated_dict

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

        dataset_payload = {}
        dataset_payload["trades"] = trades
        dataset_payload["decision_traces"] = decision_traces
        dataset_payload["runtime_events"] = runtime_events
        dataset_payload["execution_logs"] = execution_logs
        dataset_payload["orders"] = orders

        # Build pyarrow tables
        import pyarrow as pa
        import io, tarfile, hashlib
        import zstandard as zstd

        # Convert dictionary to pyarrow table helper
        def to_table(data_list):
            if not data_list:
                return pa.Table.from_arrays([pa.array([])], names=["empty"])
            import json

            if isinstance(data_list, dict):
                # Handle dictionaries (e.g. {"BTCUSD_ETHUSD": [[timestamp, value], ...]})
                rows = []
                for k, v in data_list.items():
                    if (
                        isinstance(v, list)
                        and v
                        and isinstance(v[0], list)
                        and len(v[0]) == 2
                    ):
                        for row in v:
                            rows.append(
                                {"key": k, "timestamp": row[0], "value": row[1]}
                            )
                    else:
                        rows.append(
                            {
                                "key": k,
                                "value": (
                                    json.dumps(v) if isinstance(v, (dict, list)) else v
                                ),
                            }
                        )

                if rows and "timestamp" in rows[0]:
                    keys = ["key", "timestamp", "value"]
                else:
                    keys = ["key", "value"]
                arrays = {k: [] for k in keys}
                for row in rows:
                    for k in keys:
                        arrays[k].append(row.get(k))
                return pa.Table.from_pydict(arrays)

            if isinstance(data_list[0], dict):
                # Ensure all dicts have same keys
                keys = data_list[0].keys()
                arrays = {k: [] for k in keys}
                for row in data_list:
                    for k in keys:
                        val = row.get(k)
                        # Basic handling of nested dicts (like exit_reason) -> JSON string
                        if isinstance(val, (dict, list)):
                            val = json.dumps(val)
                        arrays[k].append(val)
                return pa.Table.from_pydict(arrays)
            elif isinstance(data_list[0], list):
                # Matrix (e.g. timestamps + values)
                num_cols = len(data_list[0])
                arrays = [[] for _ in range(num_cols)]
                for row in data_list:
                    for i, val in enumerate(row):
                        arrays[i].append(val)
                names = [f"col_{i}" for i in range(num_cols)]
                if num_cols == 2:
                    names = ["timestamp", "value"]
                return pa.Table.from_arrays([pa.array(a) for a in arrays], names=names)
            return pa.Table.from_arrays([pa.array(data_list)], names=["value"])

        # 1. metadata.msgpack.zstd
        metadata_key = (
            f"research/{strategy_id}/backtests/{backtest_id}/metadata.msgpack.zstd"
        )
        await storage_service.upload_payload(metadata_key, meta_payload)

        # Extract and downsample equity curve for preview BEFORE deleting datasets
        global_ref = (
            run_dict.get("report", {}).get("datasets", {}).get("global_equity_curve")
        )
        equity_preview = []
        if global_ref and isinstance(global_ref, dict):
            global_equity_dataset_id = global_ref.get("dataset_id")
            if global_equity_dataset_id and global_equity_dataset_id in dataset_payload:
                full_equity_curve = dataset_payload[global_equity_dataset_id]
                try:
                    from crypalgos_core.reporting.compression import downsample_lttb

                    equity_preview = downsample_lttb(full_equity_curve, threshold=100)
                except Exception as e:
                    logger.error(f"Failed to downsample equity curve for preview: {e}")

        # Construct workspace tar and manifest
        import json

        manifest = {
            "workspace_version": 3,
            "engine_version": "2.1.0",
            "schema_version": 3,
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "strategy_run_id": backtest_id,
            "datasets": [],
        }

        workspace_key = (
            f"research/{strategy_id}/backtests/{backtest_id}/workspace.tar.zstd"
        )
        tar_io = io.BytesIO()

        generated_metas = {}

        with tarfile.open(fileobj=tar_io, mode="w") as tar:
            for ds_name, ds_data in dataset_payload.items():
                try:
                    tb = to_table(ds_data)
                    sink = io.BytesIO()
                    with pa.RecordBatchFileWriter(sink, tb.schema) as writer:
                        writer.write_table(tb)
                    buf = sink.getvalue()
                    checksum = hashlib.sha256(buf).hexdigest()

                    # Store inside datasets/ prefix
                    path = f"datasets/{ds_name}.arrow"
                    tarinfo = tarfile.TarInfo(name=path)
                    tarinfo.size = len(buf)
                    tar.addfile(tarinfo, io.BytesIO(buf))

                    rows = tb.num_rows
                    ds_meta = {
                        "dataset_id": ds_name,
                        "path": path,
                        "format": "arrow",
                        "compression": "zstd",  # the whole tar is zstd, arrow is uncompressed inside
                        "schema_version": 1,
                        "rows": rows,
                        "size_bytes": len(buf),
                        "checksum": checksum,
                    }
                    manifest["datasets"].append(ds_meta)
                    generated_metas[ds_name] = ds_meta

                except Exception as e:
                    logger.error(f"Failed to convert {ds_name} to Arrow: {e}")

            # Add manifest.json
            manifest_buf = json.dumps(manifest, indent=2).encode("utf-8")
            tarinfo = tarfile.TarInfo(name="manifest.json")
            tarinfo.size = len(manifest_buf)
            tar.addfile(tarinfo, io.BytesIO(manifest_buf))

        # Enrich nested dataset references in report_payload["report"] in-place
        def enrich_dataset_references(data, metas):
            if isinstance(data, dict):
                if "dataset_id" in data and data["dataset_id"] in metas:
                    data.update(metas[data["dataset_id"]])
                else:
                    for k, v in data.items():
                        enrich_dataset_references(v, metas)
            elif isinstance(data, list):
                for item in data:
                    enrich_dataset_references(item, metas)

        report_nested = report_payload.get("report", {})
        enrich_dataset_references(report_nested, generated_metas)

        # Validate that every DatasetReference in the report exists in manifest.json
        def extract_dataset_ids(data, ids):
            if isinstance(data, dict):
                if "dataset_id" in data:
                    ids.add(data["dataset_id"])
                for v in data.values():
                    extract_dataset_ids(v, ids)
            elif isinstance(data, list):
                for item in data:
                    extract_dataset_ids(item, ids)

        referenced_ids = set()
        extract_dataset_ids(report_nested, referenced_ids)
        referenced_ids = {rid for rid in referenced_ids if rid}

        manifest_ids = {ds["dataset_id"] for ds in manifest["datasets"]}

        missing_ids = referenced_ids - manifest_ids
        if missing_ids:
            raise ValueError(
                f"Workspace validation failed: Referenced dataset IDs {missing_ids} are missing from the manifest."
            )

        # 2. report.msgpack.zstd
        report_key = (
            f"research/{strategy_id}/backtests/{backtest_id}/report.msgpack.zstd"
        )
        await storage_service.upload_payload(report_key, report_payload)

        import msgpack

        artifact_size = len(msgpack.packb(report_payload, use_bin_type=True))

        # 3. workspace.tar.zstd
        compressor = zstd.ZstdCompressor(level=3)
        workspace_buf = compressor.compress(tar_io.getvalue())
        await storage_service.upload_raw_payload(workspace_key, workspace_buf)
        artifact_size += len(workspace_buf)

        # 4. runtime.arrow.zstd  (already extracted from run_dict above)
        if runtime_events:
            runtime_key = (
                f"research/{strategy_id}/backtests/{backtest_id}/runtime.arrow.zstd"
            )
            await storage_service.upload_arrow_payload(
                runtime_key, to_table(runtime_events)
            )

        # 5. decision.arrow.zstd  (already extracted from run_dict above)
        if decision_traces:
            decision_key = (
                f"research/{strategy_id}/backtests/{backtest_id}/decision.arrow.zstd"
            )
            await storage_service.upload_arrow_payload(
                decision_key, to_table(decision_traces)
            )

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
            symbol_str = ", ".join(symbols.keys()) if symbols else "BTCUSD"
        elif isinstance(symbols, list):
            symbol_str = ", ".join(symbols) if symbols else "BTCUSD"
        else:
            symbol_str = str(symbols) if symbols else "BTCUSD"

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
            "exchange": "delta",
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
