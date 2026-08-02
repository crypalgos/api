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

    @staticmethod
    def empty_ipc_stream() -> bytes:
        """A valid, empty Arrow IPC stream — for a chunk request against a
        dataset the run simply has none of (e.g. no trades yet)."""
        sink = io.BytesIO()
        with pa.ipc.new_stream(sink, pa.schema([])):
            pass
        return sink.getvalue()

    @staticmethod
    def candle_index_bounds(buf: bytes) -> "tuple[int | None, int | None]":
        """Real [min, max] candle_index for a dataset, via Arrow compute —
        no full row materialization. Used to anchor chunk_id math against the
        run's real start (indicator warmup means candle_index rarely starts
        at 0)."""
        import pyarrow.compute as pc

        with pa.ipc.open_file(io.BytesIO(buf)) as reader:
            table = reader.read_all()
        if "candle_index" not in table.column_names or len(table) == 0:
            return None, None
        col = table["candle_index"]
        return int(pc.min(col).as_py()), int(pc.max(col).as_py())

    @staticmethod
    def count_in_candle_range(buf: bytes, from_candle: int, to_candle: int) -> int:
        """Row count for a candle-index range without materializing rows —
        used by the chunk manifest endpoint to report row_counts cheaply."""
        import pyarrow.compute as pc

        with pa.ipc.open_file(io.BytesIO(buf)) as reader:
            table = reader.read_all()

        index_col = None
        for candidate in ("candle_index", "bar_index"):
            if candidate in table.column_names:
                index_col = candidate
                break

        if index_col is None:
            total_rows = len(table)
            offset = max(0, from_candle)
            if offset >= total_rows:
                return 0
            return min(max(1, to_candle - from_candle + 1), total_rows - offset)

        mask = pc.and_(
            pc.greater_equal(table[index_col], pa.scalar(from_candle)),
            pc.less_equal(table[index_col], pa.scalar(to_candle)),
        )
        return int(pc.sum(pc.cast(mask, pa.int64())).as_py() or 0)

    @staticmethod
    def slice_chunk_to_ipc(buf: bytes, from_candle: int, to_candle: int, dataset_name: str) -> bytes:
        """Slice a dataset to a candle-index range and re-serialize as a new
        Arrow IPC stream — no Python-dict/JSON intermediate. Reuses the same
        candle_index/bar_index filter (or row-offset fallback) as
        read_candle_window, but returns raw bytes for the replay chunk
        endpoints instead of decoded rows."""
        import pyarrow.compute as pc

        with pa.ipc.open_file(io.BytesIO(buf)) as reader:
            table = reader.read_all()

        if dataset_name == "indicator_snapshots" and "source" in table.column_names:
            table = table.rename_columns(
                ["datasource" if name == "source" else name for name in table.column_names]
            )

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
            sliced = table.filter(mask)
        else:
            total_rows = len(table)
            offset = max(0, from_candle)
            sliced = table.slice(0, 0) if offset >= total_rows else table.slice(
                offset, max(1, to_candle - from_candle + 1)
            )

        sink = io.BytesIO()
        with pa.ipc.new_stream(sink, sliced.schema) as writer:
            writer.write_table(sliced)
        return sink.getvalue()
