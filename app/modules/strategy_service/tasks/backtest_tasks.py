import asyncio
import logging
from datetime import datetime
from typing import Any

from crypalgos_data.exchanges.config import EXCHANGE_REGISTRY
from crypalgos_core.runtime.simulator import EngineSimulator

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
    backtest_id: str, strategy_id: str,
    start_date: datetime, end_date: datetime, initial_capital: float,
    strategy_version_id: str | None = None
) -> dict[str, Any]:
    async with job_lifecycle_context(backtest_id, "Backtest task"):
        # Load strategy and compile class first
        async with AsyncSessionLocal() as session:
            strat_class = await load_and_compile_strategy(strategy_id, session, strategy_version_id=strategy_version_id)
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
        if hasattr(strat_class, "datasources") and isinstance(strat_class.datasources, dict):
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

        commission = 0.0002 # Default maker fee
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
        }
        hash_str = json.dumps(hash_payload, sort_keys=True, separators=(",", ":"))
        run_hash = hashlib.sha256(hash_str.encode("utf-8")).hexdigest()

        USE_SANDBOX = settings.sandbox_enabled

        if not USE_SANDBOX:
            logger.info(f"[DEV] Running backtest in-process for strategy {strategy_id} (version={strategy_version_id})")


            from crypalgos_core.reporting.dataset_registry import DatasetRegistry
            DatasetRegistry._store.clear()

            simulator = EngineSimulator(
            exchange_config=EXCHANGE_REGISTRY.get(compiled_dag.get('broker', 'delta'), EXCHANGE_REGISTRY['delta'])(),
                initial_capital=initial_capital,
                leverage=leverage,
                slippage_rate=0.0002,
                taker_fee_rate=0.0005
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
                    progress_callback=flusher.update
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
                initial_capital=initial_capital
            )

        if hasattr(report, "report"):
            from dataclasses import asdict
            run_dict = asdict(report)
            raw_metrics = run_dict["report"].get("metrics", {})
            market_data_payload = run_dict.pop("market_data", [])
            report_payload = run_dict
            trades = run_dict.get("trades", [])
        else:
            run_dict = report
            raw_metrics = run_dict.get("metrics", {})
            market_data_payload = run_dict.pop("market_data", [])
            report_payload = run_dict
            trades = run_dict.get("trades", {}).get("recent_trades", [])

        g_metrics = raw_metrics.get("global", raw_metrics.get("global_metrics", raw_metrics))

        
        # S3-First storage uploads
        meta_payload = {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "initial_capital": initial_capital,
            "strategy_id": strategy_id,
            "run_id": backtest_id,
            "market_data": market_data_payload,
        }
        
        from crypalgos_core.reporting.dataset_registry import DatasetRegistry
        dataset_payload = dict(DatasetRegistry._store)
        dataset_payload["recent_trades"] = trades
        
        DatasetRegistry.clear()
        
        # Build pyarrow tables
        import pyarrow as pa
        import io, tarfile
        import zstandard as zstd
        
        # Convert dictionary to pyarrow table helper
        def to_table(data_list):
            if not data_list:
                return pa.Table.from_arrays([pa.array([])], names=["empty"])
            if isinstance(data_list[0], dict):
                # Ensure all dicts have same keys
                keys = data_list[0].keys()
                arrays = {k: [] for k in keys}
                for row in data_list:
                    for k in keys:
                        val = row.get(k)
                        # Basic handling of nested dicts (like exit_reason) -> JSON string
                        if isinstance(val, (dict, list)):
                            import json
                            val = json.dumps(val)
                        arrays[k].append(val)
                return pa.Table.from_pydict(arrays)
            elif isinstance(data_list[0], list):
                # Matrix (e.g. timestamps + values)
                num_cols = len(data_list[0])
                arrays = [ [] for _ in range(num_cols) ]
                for row in data_list:
                    for i, val in enumerate(row):
                        arrays[i].append(val)
                names = [f"col_{i}" for i in range(num_cols)]
                if num_cols == 2:
                    names = ["timestamp", "value"]
                return pa.Table.from_arrays([pa.array(a) for a in arrays], names=names)
            return pa.Table.from_arrays([pa.array(data_list)], names=["value"])

        # 1. metadata.msgpack.zstd
        metadata_key = f"research/{strategy_id}/backtests/{backtest_id}/metadata.msgpack.zstd"
        await storage_service.upload_payload(metadata_key, meta_payload)
        
        # Extract and downsample equity curve for preview BEFORE deleting datasets
        global_ref = run_dict.get("report", {}).get("datasets", {}).get("global_equity_curve")
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

        # 2. report.msgpack.zstd
        report_key = f"research/{strategy_id}/backtests/{backtest_id}/report.msgpack.zstd"
        await storage_service.upload_payload(report_key, report_payload)
        
        import msgpack
        artifact_size = len(msgpack.packb(report_payload, use_bin_type=True))
        
        # 3. workspace.tar.zstd
        workspace_key = f"research/{strategy_id}/backtests/{backtest_id}/workspace.tar.zstd"
        tar_io = io.BytesIO()
        with tarfile.open(fileobj=tar_io, mode='w') as tar:
            for ds_name, ds_data in dataset_payload.items():
                try:
                    tb = to_table(ds_data)
                    sink = io.BytesIO()
                    with pa.RecordBatchFileWriter(sink, tb.schema) as writer:
                        writer.write_table(tb)
                    buf = sink.getvalue()
                    tarinfo = tarfile.TarInfo(name=f"{ds_name}.arrow")
                    tarinfo.size = len(buf)
                    tar.addfile(tarinfo, io.BytesIO(buf))
                except Exception as e:
                    logger.error(f"Failed to convert {ds_name} to Arrow: {e}")
        
        compressor = zstd.ZstdCompressor(level=3)
        workspace_buf = compressor.compress(tar_io.getvalue())
        await storage_service.upload_raw_payload(workspace_key, workspace_buf)
        artifact_size += len(workspace_buf)
        
        # 4. runtime.arrow.zstd
        runtime_events = run_dict.get("runtime_events", [])
        if runtime_events:
            runtime_key = f"research/{strategy_id}/backtests/{backtest_id}/runtime.arrow.zstd"
            await storage_service.upload_arrow_payload(runtime_key, to_table(runtime_events))
            
        # 5. decision.arrow.zstd
        decision_traces = run_dict.get("decision_traces", [])
        if decision_traces:
            decision_key = f"research/{strategy_id}/backtests/{backtest_id}/decision.arrow.zstd"
            await storage_service.upload_arrow_payload(decision_key, to_table(decision_traces))
            
        # 6. portfolio.arrow.zstd (Placeholder for now as it's not emitted separately)
        # Actually portfolio timeline is often mixed in dataset_registry as 'global_equity_curve'




        # Build clean summary json for database index
        total_trades = g_metrics.get("total_trades", g_metrics.get("trade_count", 0))
        net_profit = g_metrics.get("net_profit", 0.0)

        expectancy = g_metrics.get("expectancy")
        if expectancy is None:
            expectancy = raw_metrics.get("distributions", {}).get("global", {}).get("expectancy")

        average_trade = g_metrics.get("average_trade")
        if average_trade is None:
            average_trade = net_profit / total_trades if total_trades > 0 else 0.0

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
            "symbol": next(iter(symbols), "BTCUSD"),
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
                        "workspace": workspace_key
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

        logger.info(f"Asynchronous Celery backtest run successfully completed and saved: {backtest_id}")
        return {"success": True, "backtest_id": backtest_id, "summary": summary_json}

@celery_app.task(name="app.modules.strategy_service.tasks.run_asynchronous_backtest_task")
def run_asynchronous_backtest_task(
    backtest_id: str, strategy_id: str,
    start_date_iso: str, end_date_iso: str, initial_capital: float,
    strategy_version_id: str | None = None
) -> dict[str, Any]:
    """Celery background task orchestrating quantitative backtest simulation."""
    start_date = datetime.fromisoformat(start_date_iso)
    end_date = datetime.fromisoformat(end_date_iso)
    return asyncio.run(_execute_backtest_internal(
        backtest_id=backtest_id,
        strategy_id=strategy_id,
        start_date=start_date,
        end_date=end_date,
        initial_capital=initial_capital,
        strategy_version_id=strategy_version_id
    ))

