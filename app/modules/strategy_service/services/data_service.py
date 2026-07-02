import logging
from app.exceptions.exceptions import ResourceNotFoundException

logger = logging.getLogger(__name__)


class DataServiceMixin:
    async def get_run_dataset_chart(
        self, user_id: str, run_id: str, dataset_name: str
    ) -> tuple[int, list]:
        """Download dataset tar archive from storage, extract the arrow file, convert to JSON and return specific chart curves."""
        from app.modules.strategy_service.utils.validators import (
            validate_run_exists,
            validate_strategy_exists,
            validate_workspace_key,
        )
        from app.modules.strategy_service.utils.formatters import (
            extract_workspace_dataset_rows,
        )

        run = await self.run_repository.get_by_id(run_id)
        validate_run_exists(run)

        strategy = await self.strategy_repository.get_by_user_and_id(
            user_id, run.strategy_id
        )
        validate_strategy_exists(strategy)

        workspace_key = (
            run.artifact_manifest.get("workspace") if run.artifact_manifest else None
        )
        validate_workspace_key(workspace_key)

        try:
            from app.modules.strategy_service.services.storage_service import (
                storage_service,
            )

            raw_zstd = await storage_service.download_raw_payload(workspace_key)
            rows = extract_workspace_dataset_rows(raw_zstd, dataset_name)
            return 200, rows
        except ResourceNotFoundException:
            raise
        except Exception as e:
            logger.error(f"Failed to download dataset {dataset_name}: {e}")
            raise ResourceNotFoundException(
                "Dataset payload not found or failed to parse."
            )

    async def get_run_artifact(
        self, user_id: str, run_id: str, artifact_type: str
    ) -> tuple[int, dict]:
        """Download a specific artifact (like report or metadata) for a run."""
        run = await self.run_repository.get_by_id(run_id)
        if not run:
            raise ResourceNotFoundException("Research run not found")

        strategy = await self.strategy_repository.get_by_user_and_id(
            user_id, run.strategy_id
        )
        if not strategy:
            raise ResourceNotFoundException("Strategy not found")

        key = (
            run.artifact_manifest.get(artifact_type) if run.artifact_manifest else None
        )
        if not key:
            raise ResourceNotFoundException(f"Run has no {artifact_type} artifact.")

        try:
            from app.modules.strategy_service.services.storage_service import (
                storage_service,
            )

            if key.endswith(".msgpack.zstd"):
                payload = await storage_service.download_payload(key)
                return 200, payload
            else:
                raise ValueError(
                    "Only msgpack JSON artifacts are supported via this endpoint"
                )
        except Exception as e:
            logger.error(f"Failed to fetch artifact {artifact_type}: {e}")
            raise ResourceNotFoundException(
                "Artifact payload not found or failed to parse."
            )
