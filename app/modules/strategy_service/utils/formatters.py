import io
import json
import logging
import tarfile

import pyarrow as pa
import zstandard as zstd

from app.exceptions.exceptions import ResourceNotFoundException

logger = logging.getLogger(__name__)


def extract_workspace_dataset_rows(raw_zstd: bytes, dataset_name: str) -> list:
    """Decompress, extract tar archive, find target dataset and parse Arrow IPC to dict list."""
    dctx = zstd.ZstdDecompressor()
    tar_io = io.BytesIO(dctx.decompress(raw_zstd))

    with tarfile.open(fileobj=tar_io, mode="r") as tar:
        # 1. Read manifest.json
        try:
            manifest_file = tar.extractfile("manifest.json")
            if not manifest_file:
                raise ResourceNotFoundException("Workspace manifest.json not found")
            manifest = json.loads(manifest_file.read().decode("utf-8"))
        except KeyError:
            raise ResourceNotFoundException("Workspace manifest.json not found")

        # 2. Find dataset in manifest
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

        # 3. Extract target file
        try:
            f = tar.extractfile(path)
            if not f:
                raise ResourceNotFoundException(
                    f"Dataset file at {path} not found in workspace archive"
                )
            buf = f.read()

            with pa.ipc.open_file(io.BytesIO(buf)) as reader:
                table = reader.read_all()
                rows = table.to_pylist()

                for row in rows:
                    for k, v in list(row.items()):
                        if isinstance(v, str) and (
                            v.startswith("{") or v.startswith("[")
                        ):
                            try:
                                row[k] = json.loads(v)
                            except Exception:
                                pass
                return rows
        except KeyError:
            raise ResourceNotFoundException(
                f"Dataset file at {path} not found in workspace archive"
            )
