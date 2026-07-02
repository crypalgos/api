import sys
import logging
import asyncio
from typing import Dict, Any, Type, Optional
from crypalgos_core.engine.strategy_base import StrategyBase
from crypalgos_core.engine.context import ExecutionMode
from app.modules.strategy_service.runner import ExecutionRunner
from app.modules.strategy_service.repositories.strategy_repository import (
    StrategyRepository,
)
from app.db.connect_db import AsyncSessionLocal

logger = logging.getLogger(__name__)


class StrategyManager:
    def __init__(self):
        self.active_runners: Dict[str, ExecutionRunner] = {}

    def _load_strategy_class_from_code(self, code_str: str) -> Type[StrategyBase]:
        """Dynamically execute strategy Python code and extract the Strategy class."""
        namespace: Dict[str, Any] = {}
        # Execute the python code in the namespace dict
        exec(code_str, namespace)

        # Find subclasses of StrategyBase
        for val in namespace.values():
            if (
                isinstance(val, type)
                and issubclass(val, StrategyBase)
                and val is not StrategyBase
            ):
                return val

        raise ValueError("No valid Strategy subclass found incompiled code.")

    async def deploy(
        self,
        strategy_id: str,
        run_id: str,
        user_id: str,
        mode: ExecutionMode = ExecutionMode.PAPER,
        initial_capital: float = 10000.0,
        leverage: int = 1,
        credential_id: Optional[str] = None,
    ) -> ExecutionRunner:
        if run_id in self.active_runners:
            raise ValueError(f"Strategy run {run_id} is already deployed and active.")

        async with AsyncSessionLocal() as session:
            repo = StrategyRepository(session)
            strategy = await repo.get_by_user_and_id(user_id, strategy_id)
            if not strategy:
                raise ValueError(
                    f"Strategy {strategy_id} not found for user {user_id}."
                )

            code_str = strategy.compiled_code
            if not code_str:
                raise ValueError("Strategy has no compiled script ready to execute.")

        # Dynamically load the Strategy class from DB-stored script
        strat_class = self._load_strategy_class_from_code(code_str)

        # ── Pre-Flight Deployment Credentials Check ─────────────────────────────
        broker_creds = None
        if mode == ExecutionMode.LIVE:
            if not credential_id:
                raise ValueError("Live trading requires a valid credential_id.")
            from app.modules.user_service.services.credential_service import (
                credential_service,
            )

            broker_creds = await credential_service.get_decrypted_broker_credential(
                credential_id
            )
            if not broker_creds:
                raise ValueError(
                    f"Active broker credentials for ID {credential_id} not found."
                )

            # Check target exchange matches strategy configuration
            # Strategy class typically has 'exchange' or similar attribute
            target_exchange = getattr(strat_class, "exchange", "delta")
            if broker_creds.exchange.value != target_exchange.lower():
                raise ValueError(
                    f"Exchange mismatch: Strategy requires '{target_exchange}', "
                    f"but credentials are for '{broker_creds.exchange.value}'."
                )

        runner = ExecutionRunner(
            strategy_run_id=run_id,
            user_id=user_id,
            strategy_class=strat_class,
            mode=mode,
            initial_capital=initial_capital,
            leverage=leverage,
            broker_credentials=broker_creds,
        )

        self.active_runners[run_id] = runner
        await runner.start()
        logger.info(f"Deployed strategy run {run_id} in {mode} mode successfully.")
        return runner

    async def stop(self, run_id: str) -> None:
        if run_id not in self.active_runners:
            logger.warning(f"Strategy run {run_id} is not active or already stopped.")
            return

        runner = self.active_runners[run_id]
        await runner.stop()
        del self.active_runners[run_id]
        logger.info(f"Stopped strategy run {run_id} successfully.")

        # Enqueue Celery S3 Archival task
        try:
            from app.modules.strategy_service.tasks.archive_tasks import (
                archive_strategy_run_task,
            )

            archive_strategy_run_task.delay(run_id)
            logger.info(f"Enqueued S3 archival task for strategy run {run_id}")
        except Exception as e:
            logger.error(f"Failed to enqueue S3 archival task: {e}")

    def get_status(self, run_id: str) -> Dict[str, Any]:
        if run_id not in self.active_runners:
            return {"status": "STOPPED"}

        runner = self.active_runners[run_id]
        balances = runner.broker.get_balances()
        return {
            "status": "RUNNING" if runner.is_running else "FAILED",
            "mode": runner.context.mode.name,
            "started_at": runner.context.started_at,
            "cash": balances.get("cash", 0.0),
            "equity": balances.get("equity", 0.0),
        }


# Global singleton
strategy_manager = StrategyManager()
