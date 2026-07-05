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

    @staticmethod
    def read_all(buf: bytes) -> List[Dict[str, Any]]:
        """Read every row, decoding stringified JSON columns."""
        with pa.ipc.open_file(io.BytesIO(buf)) as reader:
            rows = reader.read_all().to_pylist()
        return [ArrowReader._decode_json_columns(row) for row in rows]

    @staticmethod
    def read_candle_window(buf: bytes, from_candle: int, to_candle: int) -> List[Dict[str, Any]]:
        """Filter rows by candle position (candle_index / bar_index column),
        falling back to row order for datasets without one."""
        import pyarrow.compute as pc

        with pa.ipc.open_file(io.BytesIO(buf)) as reader:
            table = reader.read_all()

        index_col = None
        for candidate in ("candle_index", "bar_index"):
            if candidate in table.column_names:
                index_col = candidate
                break

        if index_col is not None:
            mask = pc.and_(
                pc.greater_equal(table[index_col], pa.scalar(from_candle)),
                pc.less_equal(table[index_col], pa.scalar(to_candle)),
            )
            rows = table.filter(mask).to_pylist()
        else:
            offset = max(0, from_candle)
            if offset >= len(table):
                return []
            rows = table.slice(offset, max(1, to_candle - from_candle + 1)).to_pylist()

        return [ArrowReader._decode_json_columns(row) for row in rows]

    @staticmethod
    def _decode_json_columns(row: Dict[str, Any]) -> Dict[str, Any]:
        for k, v in list(row.items()):
            if isinstance(v, str) and (v.startswith("{") or v.startswith("[")):
                try:
                    row[k] = json.loads(v)
                except Exception:
                    pass
        return row
