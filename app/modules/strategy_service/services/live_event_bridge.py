import asyncio
import logging
from typing import Optional

from fastapi import FastAPI

logger = logging.getLogger(__name__)

_task: Optional[asyncio.Task] = None


RECONNECT_DELAY_SECONDS = 1
MAX_RECONNECT_DELAY_SECONDS = 30


async def _listen_once() -> None:
    """Forward one Redis Pub/Sub connection until it closes or fails."""
    import redis.asyncio as aioredis

    from app.celery_app import REDIS_URL
    from app.modules.strategy_service.services.websocket_manager import (
        websocket_manager,
    )

    client = aioredis.from_url(REDIS_URL)
    pubsub = client.pubsub()
    subscribed = False
    try:
        await pubsub.psubscribe("live-session:*")
        subscribed = True
        logger.info("Live event bridge subscribed to live-session:*")

        while True:
            # `listen()` blocks indefinitely in redis-py. On this local Redis
            # deployment that eventually surfaces as a socket read timeout
            # even though the subscription is otherwise valid. A bounded
            # `get_message()` read returns None while the channel is quiet,
            # lets shutdown be prompt, and keeps the subscriber connected.
            message = await pubsub.get_message(
                ignore_subscribe_messages=True,
                timeout=1.0,
            )
            if message is None or message["type"] != "pmessage":
                continue

            channel = message["channel"]
            if isinstance(channel, bytes):
                channel = channel.decode("utf-8")
            session_id = channel.split(":", 1)[-1]

            data = message["data"]
            if isinstance(data, bytes):
                data = data.decode("utf-8")

            try:
                await websocket_manager.broadcast_to_session(session_id, data)
            except Exception:
                logger.exception(
                    "Failed forwarding live-session event for %s", session_id
                )
    finally:
        if subscribed:
            await pubsub.punsubscribe("live-session:*")
        await pubsub.aclose()
        await client.aclose()


async def _listen() -> None:
    """Keep the Redis-to-WebSocket bridge alive across transient failures."""
    reconnect_delay = RECONNECT_DELAY_SECONDS
    while True:
        try:
            await _listen_once()
            logger.warning("Live event bridge stopped listening; reconnecting")
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Live event bridge failed; reconnecting in %s seconds",
                reconnect_delay,
            )

        await asyncio.sleep(reconnect_delay)
        reconnect_delay = min(reconnect_delay * 2, MAX_RECONNECT_DELAY_SECONDS)


def _log_task_failure(task: asyncio.Task[None]) -> None:
    if task.cancelled():
        return
    exception = task.exception()
    if exception is not None:
        logger.error(
            "Live event bridge task stopped unexpectedly",
            exc_info=(type(exception), exception, exception.__traceback__),
        )


def setup_live_event_bridge(app: FastAPI) -> None:
    """Register a resilient Redis-to-WebSocket bridge for live sessions."""

    @app.on_event("startup")
    async def _startup_live_event_bridge() -> None:
        global _task
        if _task is not None and not _task.done():
            logger.warning("Live event bridge was already running")
            return

        _task = asyncio.create_task(_listen(), name="live-event-bridge")
        _task.add_done_callback(_log_task_failure)
        logger.info("Live event bridge started")

    @app.on_event("shutdown")
    async def _shutdown_live_event_bridge() -> None:
        global _task
        if _task is not None:
            _task.cancel()
            try:
                await _task
            except asyncio.CancelledError:
                pass
            finally:
                _task = None
        logger.info("Live event bridge stopped")
