import asyncio
import importlib.util
import logging
from datetime import datetime
from typing import Any, AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession
from contextlib import asynccontextmanager

from crypalgos_core.runtime.strategy_base import StrategyBase
from app.db.connect_db import AsyncSessionLocal
from app.modules.strategy_service.models.strategy_model import Strategy
from app.modules.strategy_service.tasks.ast_validator import validate_strategy_ast

logger = logging.getLogger(__name__)


async def load_and_compile_strategy(strategy_id: str, session: AsyncSession) -> type[StrategyBase]:
    """
    Fetches the strategy from the database, validates the AST,
    and dynamically compiles the python string into a StrategyBase class.
    """
    strategy = await session.get(Strategy, strategy_id)
    if not strategy:
        raise ValueError(f"Strategy {strategy_id} not found in database.")

    compiled_script = strategy.compiled_code
    validate_strategy_ast(compiled_script)

    spec = importlib.util.spec_from_loader("compiled_strategy", loader=None)
    module = importlib.util.module_from_spec(spec)
    exec(compile(compiled_script, "compiled_strategy", "exec"), module.__dict__)
    
    strat_class = next(
        (v for v in module.__dict__.values()
         if isinstance(v, type) and issubclass(v, StrategyBase) and v is not StrategyBase),
        None
    )
    if not strat_class:
        raise ValueError("No compiled StrategyBase subclass found in strategy script.")
        
    return strat_class

class AsyncProgressFlusher:
    """
    Safely bridges synchronous deep engine simulation loops with asynchronous DB writes.
    The simulation loop calls `update(completed, total)` rapidly in a sync context.
    The `start_polling` asyncio task wakes up periodically and commits the latest values to the DB.
    """
    def __init__(self, model_class, run_id: str, flush_interval: float = 2.0):
        self.model_class = model_class
        self.run_id = run_id
        self.flush_interval = flush_interval
        self._completed = 0
        self._total = 0
        self._last_flushed_completed = -1
        self._is_running = True

    def update(self, completed: int, total: int):
        self._completed = completed
        self._total = total

    def stop(self):
        self._is_running = False

    async def start_polling(self):
        while self._is_running:
            await asyncio.sleep(self.flush_interval)
            
            c = self._completed
            t = self._total
            
            # Only hit the DB if progress actually changed
            if c > self._last_flushed_completed and t > 0:
                self._last_flushed_completed = c
                try:
                    async with AsyncSessionLocal() as session:
                        async with session.begin():
                            run = await session.get(self.model_class, self.run_id)
                            if run and run.status == "RUNNING":
                                run.progress_json = {
                                    "completed": c,
                                    "total": t,
                                    "percentage": round((c / t) * 100, 2)
                                }
                except Exception as e:
                    logger.warning(f"Failed to flush progress for {self.run_id}: {e}")

@asynccontextmanager
async def job_lifecycle_context(
    model_class: type, run_id: str, task_name: str
) -> AsyncGenerator[None, None]:
    """
    Handles the common boilerplate for background research jobs:
    - Disposing sync engines (for Celery forks)
    - Marking job as RUNNING and tracking started_at
    - Catching exceptions and marking FAILED with truncated error messages
    """
    # Dispose of inherited connection descriptors in child process prefork pools
    from app.db.connect_db import engine
    engine.sync_engine.dispose()

    logger.info(f"{task_name} started for run_id={run_id}")

    # Mark as RUNNING
    async with AsyncSessionLocal() as session:
        async with session.begin():
            run = await session.get(model_class, run_id)
            if not run:
                raise ValueError(f"{model_class.__name__} {run_id} not found.")
            run.status = "RUNNING"
            run.started_at = datetime.utcnow()

    try:
        yield  # Execute the core engine logic
        
    except Exception as e:
        logger.error(f"{task_name} run {run_id} failed: {e}")
        err_msg = str(e)[:500]
        async with AsyncSessionLocal() as session:
            async with session.begin():
                run = await session.get(model_class, run_id)
                if run:
                    run.status = "FAILED"
                    run.completed_at = datetime.utcnow()
                    if hasattr(run, "error_message"):
                        run.error_message = err_msg
                    # Specific fallback for backtests which use metrics_json
                    elif hasattr(run, "metrics_json"):
                        metrics = run.metrics_json or {}
                        metrics["error"] = err_msg
                        run.metrics_json = metrics
        # Re-raise so celery marks the task as failed
        raise e
