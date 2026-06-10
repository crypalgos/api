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
    backtest_id: str, strategy_id: str,
    start_date: datetime, end_date: datetime, initial_capital: float
) -> dict[str, Any]:
    # Normalize inputs
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
                start_date=start_date,
                end_date=end_date,
                initial_capital=initial_capital
            )

        # 6. Map reporting sections to database columns
        # The new multi-symbol reporting engine returns a structured dictionary
        metrics = report.get("metrics", {})
        
        charting = {
            "datasets": report.get("datasets", {}),
            "trades": report.get("trades", {}),
            "monthly": report.get("monthly", {}),
            "correlations": report.get("correlations", {})
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
    backtest_id: str, strategy_id: str,
    start_date_iso: str, end_date_iso: str, initial_capital: float
) -> dict[str, Any]:
    """Celery background task orchestrating quantitative backtest simulation."""
    start_date = datetime.fromisoformat(start_date_iso)
    end_date = datetime.fromisoformat(end_date_iso)
    return asyncio.run(_execute_backtest_internal(
        backtest_id=backtest_id,
        strategy_id=strategy_id,
        start_date=start_date,
        end_date=end_date,
        initial_capital=initial_capital
    ))
