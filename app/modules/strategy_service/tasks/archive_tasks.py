import io
import json
import logging
import tarfile
import pyarrow as pa
import zstandard as zstd
from typing import List, Dict, Any
from sqlalchemy import select, delete
from app.celery_app import celery_app
from app.db.connect_db import AsyncSessionLocal
from app.modules.strategy_service.models.strategy_event_model import StrategyEvent
from app.modules.strategy_service.services.storage_service import storage_service

logger = logging.getLogger(__name__)


def to_arrow_bytes(data_list: List[Dict[str, Any]]) -> bytes:
    """Helper to convert a list of dictionaries to PyArrow IPC Table bytes."""
    if not data_list:
        table = pa.Table.from_arrays([pa.array([])], names=["empty"])
    else:
        # Build schema dynamically from first item keys
        schema_dict = {}
        for key in data_list[0].keys():
            schema_dict[key] = pa.array([item.get(key) for item in data_list])
        table = pa.Table.from_pydict(schema_dict)

    sink = io.BytesIO()
    with pa.RecordBatchFileWriter(sink, table.schema) as writer:
        writer.write_table(table)
    return sink.getvalue()


@celery_app.task(
    name="app.modules.strategy_service.tasks.archive_strategy_run_task",
    bind=True,
    max_retries=5,
    default_retry_delay=60,
)
def archive_strategy_run_task(self, run_id: str):
    """Celery background task that packages strategy DB events into workspace.tar.zstd and uploads to S3."""
    import asyncio

    # Run the async archiving process inside the celery sync execution thread
    return asyncio.run(self._archive_async(run_id))


async def _archive_async(self, run_id: str):
    logger.info(f"Starting async archival for strategy run {run_id}")

    # 1. Query events from PostgreSQL strategy_events table
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(StrategyEvent).where(StrategyEvent.strategy_run_id == run_id)
        )
        db_events = result.scalars().all()

    if not db_events:
        logger.warning(
            f"No events found in DB for strategy run {run_id}; skipping archival."
        )
        return

    # Categorize events dynamically
    EVENT_CATEGORY_MAPPING = {
        "OrderFilledEvent": "trades",
        "OrderSubmittedEvent": "orders",
        "OrderAcceptedEvent": "orders",
        "OrderCancelledEvent": "orders",
    }

    categorized = {"trades": [], "orders": []}
    manifest = {
        "workspace_schema": 1,
        "report_schema": 1,
        "event_schema": 1,
        "engine_version": "1.0.0",
        "run_id": run_id,
        "events_count": len(db_events),
    }

    for ev in db_events:
        category = EVENT_CATEGORY_MAPPING.get(ev.event_type)
        if category:
            categorized[category].append(ev.payload)

    trades = categorized["trades"]
    orders = categorized["orders"]
    # We can extract equity values if present, or write other states

    # 2. Build pyarrow files
    trades_arrow = to_arrow_bytes(trades)
    orders_arrow = to_arrow_bytes(orders)
    manifest_json = json.dumps(manifest, indent=2).encode("utf-8")

    # 3. Create .tar.zstd archive in memory
    tar_io = io.BytesIO()
    cctx = zstd.ZstdCompressor(level=3)

    with cctx.stream_writer(tar_io) as compressor:
        with tarfile.open(fileobj=compressor, mode="w|") as tar:
            # Trades
            t_info = tarfile.TarInfo(name="trades.arrow")
            t_info.size = len(trades_arrow)
            tar.addfile(t_info, io.BytesIO(trades_arrow))

            # Orders
            o_info = tarfile.TarInfo(name="orders.arrow")
            o_info.size = len(orders_arrow)
            tar.addfile(o_info, io.BytesIO(orders_arrow))

            # Manifest
            m_info = tarfile.TarInfo(name="manifest.json")
            m_info.size = len(manifest_json)
            tar.addfile(m_info, io.BytesIO(manifest_json))

    archive_bytes = tar_io.getvalue()
    s3_key = f"workspaces/{run_id}/workspace.tar.zstd"

    # 4. Upload archive to S3
    logger.info(f"Uploading archive to S3: {s3_key}")
    await storage_service.upload_raw_payload(s3_key, archive_bytes)

    # 5. Verify upload (check S3 object details)
    try:
        await asyncio.to_thread(
            storage_service.s3_client.head_object,
            Bucket=storage_service.s3_bucket,
            Key=s3_key,
        )
        logger.info(f"S3 upload verified for strategy run {run_id}")

        # 6. Delete raw database events after verified upload
        async with AsyncSessionLocal() as session:
            await session.execute(
                delete(StrategyEvent).where(StrategyEvent.strategy_run_id == run_id)
            )
            await session.commit()
            logger.info(f"Pruned DB events for strategy run {run_id} successfully.")

    except Exception as e:
        logger.error(f"Archiving verification failed for strategy run {run_id}: {e}")
        # Celery task retry logic
        raise self.retry(exc=e)


# Bind the helper function to the Celery class method
archive_strategy_run_task._archive_async = _archive_async
