import io
import json
from typing import List, Dict, Any
import pyarrow as pa


class ArrowReader:
    """Handles reading, slicing, and converting Apache Arrow IPC payloads into dictionary rows."""

    @staticmethod
    def read_window(
        buf: bytes, start_bar: int, end_bar: int, dataset_name: str
    ) -> List[Dict[str, Any]]:
        with pa.ipc.open_file(io.BytesIO(buf)) as reader:
            table = reader.read_all()
            total_rows = len(table)

            # Bound offsets
            offset = max(0, start_bar)
            limit = max(1, end_bar - start_bar + 1)

            if offset >= total_rows:
                return []

            sliced = table.slice(offset, min(limit, total_rows - offset))
            rows = sliced.to_pylist()

            # Map source to datasource for indicator_snapshots
            if dataset_name == "indicator_snapshots":
                for row in rows:
                    if "source" in row:
                        row["datasource"] = row.pop("source")

            # Parse any stringified JSON dictionaries
            for row in rows:
                for k, v in list(row.items()):
                    if isinstance(v, str) and (v.startswith("{") or v.startswith("[")):
                        try:
                            row[k] = json.loads(v)
                        except Exception:
                            pass
            return rows

    @staticmethod
    def count_rows(buf: bytes) -> int:
        with pa.ipc.open_file(io.BytesIO(buf)) as reader:
            table = reader.read_all()
            return len(table)
