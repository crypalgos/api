import asyncio
import logging
import os
import tempfile
import importlib.util
from datetime import datetime
from typing import Any

from crypalgos_core.runtime.simulator import EngineSimulator
from crypalgos_core.runtime.strategy_base import StrategyBase

from app.celery_app import celery_app
from app.config.settings import settings
from app.db.connect_db import AsyncSessionLocal
from app.modules.strategy_service.models.backtest_model import Backtest
from app.modules.strategy_service.models.strategy_model import Strategy
from app.modules.strategy_service.tasks.task_utils import (
    job_lifecycle_context, load_and_compile_strategy, AsyncProgressFlusher
)
from app.modules.strategy_service.tasks.sandbox import run_in_sandbox

logger = logging.getLogger(__name__)

async def _execute_backtest_internal(
    backtest_id: str, strategy_id: str, exchange: str, symbol: str,
    start_date: datetime, end_date: datetime, initial_capital: float, leverage: int
) -> dict[str, Any]:
    # Normalize inputs
    symbol = symbol.replace("/", "").replace("-", "").upper()
    exchange = exchange.strip().lower()

    async with job_lifecycle_context(Backtest, backtest_id, "Backtest task"):
        # Load strategy and determine execution mode
        async with AsyncSessionLocal() as session:
            strategy = await session.get(Strategy, strategy_id)
            if not strategy:
                raise ValueError(f"Strategy {strategy_id} not found in database.")
            
        USE_SANDBOX = settings.sandbox_enabled

        if not USE_SANDBOX:
            # ── In-process execution (local dev / testing) ─────────────────────
            logger.info(f"[DEV] Running backtest in-process for strategy {strategy_id}")
            async with AsyncSessionLocal() as session:
                strat_class = await load_and_compile_strategy(strategy_id, session)

            simulator = EngineSimulator(
                initial_capital=initial_capital,
                leverage=leverage,
                slippage_rate=0.0002,
                maker_fee_rate=0.0002,
                taker_fee_rate=0.0004
            )
            
            # Setup progress flusher
            flusher = AsyncProgressFlusher(Backtest, backtest_id)
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
            # ── Secure Docker gVisor Sandbox Execution ─────────────────────────
            # Currently does not support real-time progress callbacks across container boundary
            report = await asyncio.to_thread(
                run_in_sandbox,
                strategy=strategy,
                exchange=exchange,
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
                initial_capital=initial_capital,
                leverage=leverage
            )

        # 6. Construct charting metrics mapping
        metrics = {
            "net_profit": report.get("net_profit", 0.0),
            "profit_pct": (report.get("net_profit", 0.0) / initial_capital) * 100.0,
            "total_trades": len(report.get("trades", [])),
            "win_rate": report.get("win_rate", 0.0),
            "profit_factor": report.get("profit_factor", 0.0),
            "sharpe_ratio": report.get("sharpe_ratio", 0.0),
            "max_drawdown": report.get("max_drawdown", 0.0),
            "final_balance": report.get("final_balance", initial_capital)
        }

        # Sampling charting timeline arrays to maximum 1,000 points
        raw_equity = report.get("equity_curve", [])
        raw_drawdown = report.get("drawdown_curve", [])
        
        def downsample(timeline: list, target: int = 1000) -> list:
            n = len(timeline)
            if n <= target:
                return timeline
            step = n // target
            return [timeline[i] for i in range(0, n, step)] + [timeline[-1]]

        charting = {
            "trades": report.get("trades", []),
            "equity_curve": downsample(raw_equity),
            "drawdown_curve": downsample(raw_drawdown)
        }

        # Update DB with results
        async with AsyncSessionLocal() as session:
            async with session.begin():
                bt = await session.get(Backtest, backtest_id)
                bt.status = "COMPLETED"
                bt.completed_at = datetime.utcnow()
                bt.metrics_json = metrics
                bt.charting_json = charting

        logger.info(f"Asynchronous Celery backtest run successfully saved: {backtest_id}")
        return {"success": True, "backtest_id": backtest_id, "metrics": metrics}

@celery_app.task(name="app.modules.strategy_service.tasks.run_asynchronous_backtest_task")
def run_asynchronous_backtest_task(
    backtest_id: str, strategy_id: str, exchange: str, symbol: str,
    start_date_iso: str, end_date_iso: str, initial_capital: float, leverage: int
) -> dict[str, Any]:
    """Celery background task orchestrating quantitative backtest simulation."""
    start_date = datetime.fromisoformat(start_date_iso)
    end_date = datetime.fromisoformat(end_date_iso)
    return asyncio.run(_execute_backtest_internal(
        backtest_id=backtest_id,
        strategy_id=strategy_id,
        exchange=exchange,
        symbol=symbol,
        start_date=start_date,
        end_date=end_date,
        initial_capital=initial_capital,
        leverage=leverage
    ))
