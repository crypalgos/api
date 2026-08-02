import logging
import re
from app.exceptions.exceptions import ResourceNotFoundException

logger = logging.getLogger(__name__)

# Matches crypalgos_core.montecarlo.reporting.build_montecarlo_report()'s
# output_dir/datasets/montecarlo/*.arrow filenames (ADR-009 — Scenario
# Framework freeze) plus the API-layer real_equity.arrow — allowlisted so
# dataset_name can't be used to probe arbitrary S3 keys.
_MONTECARLO_DATASET_NAMES = frozenset({
    "sample_paths", "percentile_bands", "simulation_summary", "distributions", "real_equity",
})

# Matches crypalgos_core.walkforward.reporting.build_walkforward_report()'s
# output_dir/datasets/walkforward/*.arrow filenames — unlike Monte Carlo's
# fixed dataset names, these are dynamic per-window (one train/validation
# pair per window, window count varies per run), so this is a pattern
# check rather than an exact-name allowlist — still rejects anything that
# isn't one of the exact shapes this writer produces.
_WALKFORWARD_DATASET_PATTERN = re.compile(r"^(equity|rolling|window_\d+_(train|validation))$")


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

    async def get_montecarlo_dataset(
        self, user_id: str, run_id: str, dataset_name: str
    ) -> tuple[int, list]:
        """Download one of the flat Monte Carlo chart datasets (equity_fan,
        returns, drawdowns, sharpes) — these are standalone Arrow IPC files,
        not bundled inside a workspace.tar.zstd like backtest datasets."""
        from app.modules.strategy_service.utils.validators import (
            validate_run_exists,
            validate_strategy_exists,
        )
        from app.utils.artifact_paths import ArtifactPaths

        if dataset_name not in _MONTECARLO_DATASET_NAMES:
            raise ResourceNotFoundException(f"Unknown Monte Carlo dataset '{dataset_name}'.")

        run = await self.run_repository.get_by_id(run_id)
        validate_run_exists(run)

        strategy = await self.strategy_repository.get_by_user_and_id(
            user_id, run.strategy_id
        )
        validate_strategy_exists(strategy)

        paths = ArtifactPaths(strategy_id=run.strategy_id, run_id=run_id, kind="montecarlos")
        key = paths.montecarlo_dataset(dataset_name)

        try:
            import io
            import pyarrow as pa
            from app.modules.strategy_service.services.storage_service import (
                storage_service,
            )

            raw = await storage_service.download_raw_payload(key)
            with pa.ipc.open_file(io.BytesIO(raw)) as reader:
                table = reader.read_all()
            return 200, table.to_pylist()
        except ResourceNotFoundException:
            raise
        except Exception as e:
            logger.error(f"Failed to download Monte Carlo dataset {dataset_name}: {e}")
            raise ResourceNotFoundException(
                "Dataset payload not found or failed to parse."
            )

    async def get_walkforward_dataset(
        self, user_id: str, run_id: str, dataset_name: str
    ) -> tuple[int, list]:
        """Download one of the walk-forward chart datasets (equity, rolling,
        or a per-window window_{id}_train/window_{id}_validation pair) —
        standalone Arrow IPC files, not bundled inside a workspace.tar.zstd."""
        from app.modules.strategy_service.utils.validators import (
            validate_run_exists,
            validate_strategy_exists,
        )
        from app.utils.artifact_paths import ArtifactPaths

        if not _WALKFORWARD_DATASET_PATTERN.fullmatch(dataset_name):
            raise ResourceNotFoundException(f"Unknown walk-forward dataset '{dataset_name}'.")

        run = await self.run_repository.get_by_id(run_id)
        validate_run_exists(run)

        strategy = await self.strategy_repository.get_by_user_and_id(
            user_id, run.strategy_id
        )
        validate_strategy_exists(strategy)

        paths = ArtifactPaths(strategy_id=run.strategy_id, run_id=run_id, kind="walkforwards")
        key = paths.walkforward_dataset(dataset_name)

        try:
            import io
            import pyarrow as pa
            from app.modules.strategy_service.services.storage_service import (
                storage_service,
            )

            raw = await storage_service.download_raw_payload(key)
            with pa.ipc.open_file(io.BytesIO(raw)) as reader:
                table = reader.read_all()
            return 200, table.to_pylist()
        except ResourceNotFoundException:
            raise
        except Exception as e:
            logger.error(f"Failed to download walk-forward dataset {dataset_name}: {e}")
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
            # Optimization/walkforward/montecarlo tasks store artifacts in the
            # typed columns, not artifact_manifest (only backtests set that).
            key = {
                "report": run.report_s3_key,
                "metadata": run.metadata_s3_key,
            }.get(artifact_type)
        if not key:
            raise ResourceNotFoundException(f"Run has no {artifact_type} artifact.")

        try:
            from app.modules.strategy_service.services.storage_service import (
                storage_service,
            )

            if key.endswith(".msgpack.zstd"):
                payload = await storage_service.download_payload(key)
                return 200, payload
            elif key.endswith(".msgpack"):
                # Split-artifact sections (report_split.py) are written
                # without zstd — small enough that compression isn't worth
                # the extra decode step. Proxied through this same endpoint
                # as plain JSON, same as the legacy monolithic report.
                payload = await storage_service.download_msgpack_raw(key)
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
