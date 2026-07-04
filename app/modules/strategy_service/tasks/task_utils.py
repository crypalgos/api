import asyncio
import importlib.util
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import AsyncGenerator

from crypalgos_core.engine.strategy_base import StrategyBase
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.connect_db import AsyncSessionLocal
from app.modules.strategy_service.models.strategy_model import Strategy
from app.modules.strategy_service.tasks.ast_validator import validate_strategy_ast

logger = logging.getLogger(__name__)


async def load_and_compile_strategy(
    strategy_id: str, session: AsyncSession, strategy_version_id: str | None = None
) -> type[StrategyBase]:
    """
    Fetches the strategy or strategy version from the database, validates the AST,
    and dynamically compiles the python string into a StrategyBase class.
    """
    if strategy_version_id:
        from app.modules.strategy_service.models.strategy_version_model import (
            StrategyVersion,
        )

        version = await session.get(StrategyVersion, strategy_version_id)
        if not version:
            raise ValueError(
                f"StrategyVersion {strategy_version_id} not found in database."
            )
        compiled_script = version.compiled_code
    else:
        strategy = await session.get(Strategy, strategy_id)
        if not strategy:
            raise ValueError(f"Strategy {strategy_id} not found in database.")
        compiled_script = strategy.compiled_code

    validate_strategy_ast(compiled_script)

    spec = importlib.util.spec_from_loader("compiled_strategy", loader=None)
    if not spec:
        raise ValueError("Failed to create import spec for strategy.")
    module = importlib.util.module_from_spec(spec)
    exec(compile(compiled_script, "compiled_strategy", "exec"), module.__dict__)

    strat_class = next(
        (
            v
            for v in module.__dict__.values()
            if isinstance(v, type)
            and issubclass(v, StrategyBase)
            and v is not StrategyBase
        ),
        None,
    )
    if not strat_class:
        raise ValueError("No compiled StrategyBase subclass found in strategy script.")

    return strat_class


from app.modules.strategy_service.models.research_run_model import ResearchRun


class AsyncProgressFlusher:
    """
    Safely bridges synchronous deep engine simulation loops with asynchronous DB writes.
    The simulation loop calls `update(completed, total)` rapidly in a sync context.
    The `start_polling` asyncio task wakes up periodically and commits the latest values to the DB.
    """

    def __init__(self, run_id: str, run_type: str, flush_interval: float = 2.0):
        self.run_id = run_id
        self.run_type = run_type
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
                    percent = int((c / t) * 100)
                    progress_info = {"progress_percent": percent}
                    if self.run_type == "BACKTEST":
                        progress_info.update(
                            {"processed_candles": c, "total_candles": t}
                        )
                    elif self.run_type == "OPTIMIZATION":
                        progress_info.update(
                            {"completed_combinations": c, "total_combinations": t}
                        )
                    elif self.run_type == "WALKFORWARD":
                        progress_info.update(
                            {"completed_windows": c, "total_windows": t}
                        )
                    elif self.run_type == "MONTECARLO":
                        progress_info.update(
                            {"completed_simulations": c, "total_simulations": t}
                        )

                    async with AsyncSessionLocal() as session:
                        async with session.begin():
                            run = await session.get(ResearchRun, self.run_id)
                            if run and run.status == "RUNNING":
                                run.progress_percent = percent
                                run.progress_json = progress_info
                except Exception as e:
                    logger.warning(f"Failed to flush progress for {self.run_id}: {e}")


@asynccontextmanager
async def job_lifecycle_context(
    run_id: str, task_name: str
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
            run = await session.get(ResearchRun, run_id)
            if not run:
                raise ValueError(f"ResearchRun {run_id} not found.")
            run.status = "RUNNING"
            run.started_at = datetime.utcnow()

    try:
        yield  # Execute the core logic

    except Exception as e:
        logger.error(f"{task_name} run {run_id} failed: {e}")
        err_msg = str(e)[:500]
        async with AsyncSessionLocal() as session:
            async with session.begin():
                run = await session.get(ResearchRun, run_id)
                if run:
                    run.status = "FAILED"
                    run.completed_at = datetime.utcnow()
                    run.progress_percent = 100
                    if not run.summary_json:
                        run.summary_json = {}
                    summary = dict(run.summary_json)
                    summary["error"] = err_msg
                    run.summary_json = summary
        # Re-raise so celery marks the task as failed
        raise e


def to_table(data_list):
    import pyarrow as pa
    import json

    if not data_list:
        return pa.Table.from_arrays([pa.array([])], names=["empty"])

    if isinstance(data_list, dict):
        # Handle dictionaries (e.g. {"BTCUSD_ETHUSD": [[timestamp, value], ...]})
        rows = []
        for k, v in data_list.items():
            if isinstance(v, list) and v and isinstance(v[0], list) and len(v[0]) == 2:
                for row in v:
                    rows.append({"key": k, "timestamp": row[0], "value": row[1]})
            else:
                rows.append(
                    {
                        "key": k,
                        "value": (json.dumps(v, default=str) if isinstance(v, (dict, list)) else v),
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
        # Store heterogeneous dicts as JSON payload column to avoid Arrow schema conflicts
        payloads = [json.dumps(row, default=str) for row in data_list]
        return pa.Table.from_arrays([pa.array(payloads)], names=["payload"])
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


def extract_dataset_ids(data, ids):
    if isinstance(data, dict):
        if "dataset_id" in data:
            ids.add(data["dataset_id"])
        for v in data.values():
            extract_dataset_ids(v, ids)
    elif isinstance(data, list):
        for item in data:
            extract_dataset_ids(item, ids)


