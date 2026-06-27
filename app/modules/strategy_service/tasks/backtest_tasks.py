import asyncio
import logging
from datetime import datetime
from typing import Any

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


            simulator = EngineSimulator(
                initial_capital=initial_capital,
                leverage=leverage,
                slippage_rate=0.0002,
                maker_fee_rate=0.0002,
                taker_fee_rate=0.0004
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

        raw_metrics = report.get("metrics", {})
        g_metrics = raw_metrics.get("global", raw_metrics.get("global_metrics", raw_metrics))

        charting = {
            "datasets": report.get("datasets", {}),
            "trades": report.get("trades", {}),
            "monthly": report.get("monthly", {}),
            "correlations": report.get("correlations", {})
        }

        # S3-First storage uploads
        meta_payload = {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "initial_capital": initial_capital,
            "strategy_id": strategy_id,
            "run_id": backtest_id,
        }
        report_payload = {
            "metrics": raw_metrics,
            "charting": charting,
        }
        from crypalgos_core.reporting.dataset_registry import DatasetRegistry
        dataset_payload = dict(DatasetRegistry._store)
        dataset_payload["recent_trades"] = report.get("trades", {}).get("recent_trades", [])
        
        # Clear registry after reading to prevent memory growth
        DatasetRegistry.clear()

        # Measure size of S3 artifacts
        import msgpack
        artifact_size = len(msgpack.packb(report_payload, use_bin_type=True))

        metadata_key = f"research/{strategy_id}/backtests/{backtest_id}/metadata.msgpack.zstd"
        report_key = f"research/{strategy_id}/backtests/{backtest_id}/report.msgpack.zstd"
        dataset_key = f"research/{strategy_id}/backtests/{backtest_id}/datasets.arrow.zstd"

        await storage_service.upload_payload(metadata_key, meta_payload)
        await storage_service.upload_payload(report_key, report_payload)
        await storage_service.upload_payload(dataset_key, dataset_payload)

        # Extract and downsample equity curve for preview
        global_ref = report.get("datasets", {}).get("global_equity_curve")
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
                    run.metadata_s3_key = metadata_key
                    run.report_s3_key = report_key
                    run.dataset_s3_key = dataset_key
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

