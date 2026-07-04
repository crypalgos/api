import logging
from app.exceptions.exceptions import ResourceNotFoundException, ValidationException
from app.modules.replay.utils.workspace_reader import WorkspaceReader
from app.modules.replay.utils.arrow_reader import ArrowReader
from app.modules.strategy_service.repositories.strategy_repository import (
    StrategyRepository,
)
from app.modules.strategy_service.repositories.research_run_repository import (
    ResearchRunRepository,
)

logger = logging.getLogger(__name__)


class ReplayService:
    """Orchestrator for managing user permission checking and delegating table reading queries."""

    def __init__(
        self,
        strategy_repository: StrategyRepository,
        run_repository: ResearchRunRepository,
    ):
        self.strategy_repository = strategy_repository
        self.run_repository = run_repository

    async def _resolve_workspace_key(self, user_id: str, run_id: str) -> str:
        run = await self.run_repository.get_by_id(run_id)
        if not run:
            raise ResourceNotFoundException("Research run not found")

        strategy = await self.strategy_repository.get_by_user_and_id(
            user_id, run.strategy_id
        )
        if not strategy:
            raise ResourceNotFoundException("Strategy not found")

        workspace_key = (
            run.artifact_manifest.get("workspace") if run.artifact_manifest else None
        )
        if not workspace_key:
            raise ResourceNotFoundException("Run dataset has no workspace key.")

        return workspace_key

    async def get_manifest(self, user_id: str, run_id: str) -> tuple[int, dict]:
        """Fetch general manifest info for windowed replay."""
        workspace_key = await self._resolve_workspace_key(user_id, run_id)
        reader = WorkspaceReader(workspace_key)
        try:
            candles_bytes = await reader.get_dataset_bytes("candles")
        except ResourceNotFoundException:
            # A workspace without candles has nothing to replay
            raise ResourceNotFoundException("Workspace has no candles dataset.")
        try:
            bar_count = ArrowReader.count_rows(candles_bytes)
        except Exception as e:
            logger.error(f"Corrupt candles dataset for run {run_id}: {e}")
            raise ValidationException("Workspace artifact is corrupt: unreadable candles dataset.")

        return 200, {
            "workspace_version": 1,
            "schema_version": 1,
            "datasets": [
                "candles",
                "indicator_snapshots",
                "runtime_events",
                "decision_traces",
            ],
            "bar_count": bar_count,
        }

    async def get_dataset_window(
        self, user_id: str, run_id: str, dataset_name: str, start_bar: int, end_bar: int
    ) -> tuple[int, list]:
        """Fetch windowed slice of a dataset for replay using start/end indices."""
        # Missing run/strategy/workspace/dataset propagates as 404; a dataset that
        # exists but cannot be decoded is a corrupt artifact, not a missing one.
        workspace_key = await self._resolve_workspace_key(user_id, run_id)
        reader = WorkspaceReader(workspace_key)
        buf = await reader.get_dataset_bytes(dataset_name)
        try:
            rows = ArrowReader.read_window(buf, start_bar, end_bar, dataset_name)
        except Exception as e:
            logger.error(f"Corrupt dataset {dataset_name} for run {run_id}: {e}")
            raise ValidationException(f"Workspace artifact is corrupt: dataset '{dataset_name}' failed to decode.")
        return 200, rows
