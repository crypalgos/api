import io
import tarfile
import json
import zstandard as zstd
from app.exceptions.exceptions import ResourceNotFoundException
from app.modules.replay.utils.cache import workspace_cache


class WorkspaceReader:
    """Manages downloading, caching, and decompressing the S3 workspace archives."""

    def __init__(self, workspace_key: str):
        self.workspace_key = workspace_key

    async def _get_decompressed_archive(self) -> bytes:
        """Download raw S3 payload and decompress zstd."""
        cached = workspace_cache.get(self.workspace_key)
        if cached:
            return cached

        from app.modules.strategy_service.services.storage_service import (
            storage_service,
        )

        raw_zstd = await storage_service.download_raw_payload(self.workspace_key)

        dctx = zstd.ZstdDecompressor()
        decompressed = dctx.decompress(raw_zstd)

        workspace_cache.set(self.workspace_key, decompressed)
        return decompressed

    async def get_manifest(self) -> dict:
        """Read and parse the workspace manifest.json."""
        archive_bytes = await self._get_decompressed_archive()
        tar_io = io.BytesIO(archive_bytes)
        with tarfile.open(fileobj=tar_io, mode="r") as tar:
            try:
                manifest_file = tar.extractfile("manifest.json")
                if not manifest_file:
                    raise ResourceNotFoundException("Workspace manifest.json not found")
                return json.loads(manifest_file.read().decode("utf-8"))
            except KeyError:
                raise ResourceNotFoundException("Workspace manifest.json not found")

    async def get_dataset_bytes(self, dataset_name: str) -> bytes:
        """Extract a single arrow file's raw bytes from the tar archive."""
        archive_bytes = await self._get_decompressed_archive()
        tar_io = io.BytesIO(archive_bytes)

        with tarfile.open(fileobj=tar_io, mode="r") as tar:
            try:
                manifest_file = tar.extractfile("manifest.json")
                if not manifest_file:
                    raise ResourceNotFoundException("Workspace manifest.json not found")
                manifest = json.loads(manifest_file.read().decode("utf-8"))
            except KeyError:
                raise ResourceNotFoundException("Workspace manifest.json not found")

            datasets_list = manifest.get("datasets", [])
            dataset_meta = None
            for ds in datasets_list:
                if ds.get("dataset_id") == dataset_name:
                    dataset_meta = ds
                    break

            if not dataset_meta:
                raise ResourceNotFoundException(
                    f"Dataset {dataset_name} not found in manifest"
                )

            path = dataset_meta.get("path")
            if not path:
                raise ResourceNotFoundException(
                    f"Path for dataset {dataset_name} not found in manifest"
                )

            try:
                f = tar.extractfile(path)
                if not f:
                    raise ResourceNotFoundException(
                        f"Dataset file at {path} not found in archive"
                    )
                return f.read()
            except KeyError:
                raise ResourceNotFoundException(
                    f"Dataset file at {path} not found in archive"
                )
