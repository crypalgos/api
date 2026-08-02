import asyncio
import inspect
import logging
from collections import defaultdict
from typing import Any, Awaitable, Callable, Optional

from crypalgos_data.stream.subscriber import StreamSubscriber

from app.config.settings import settings

logger = logging.getLogger(__name__)
Callback = Callable[[str, dict[str, Any]], Awaitable[None] | None]


class LiveFeedSubscriber:
    """One decoded ZMQ feed, routed in-memory by message symbol.

    The dedicated streamer-service owns exchange connections. This process
    decodes each ZMQ frame once, then hands the same data object only to local
    consumers for its symbol. Explicit global callbacks preserve the legacy
    all-symbol ExecutionRunner path without making it the default.
    """

    def __init__(self, address: Optional[str] = None) -> None:
        self.address = address or settings.streamer_zmq_address
        self._subscriber = StreamSubscriber(address=self.address)
        self._callbacks_by_symbol: dict[str, list[Callback]] = defaultdict(list)
        self._global_callbacks: list[Callback] = []
        self.task: Optional[asyncio.Task] = None
        self.is_running = False

    def register_callback(self, symbol: str, callback: Callback) -> None:
        """Register a consumer for one normalized market symbol."""
        self._callbacks_by_symbol[symbol.upper()].append(callback)

    def unregister_callback(self, symbol: str, callback: Callback) -> None:
        callbacks = self._callbacks_by_symbol.get(symbol.upper())
        if callbacks is None:
            return
        if callback in callbacks:
            callbacks.remove(callback)
        if not callbacks:
            self._callbacks_by_symbol.pop(symbol.upper(), None)

    def register_global_callback(self, callback: Callback) -> None:
        """Register the exceptional all-symbol consumer path explicitly."""
        self._global_callbacks.append(callback)

    def unregister_global_callback(self, callback: Callback) -> None:
        if callback in self._global_callbacks:
            self._global_callbacks.remove(callback)

    async def start(self) -> None:
        if self.is_running:
            return
        logger.info("Connecting to streamer-service ZMQ feed at %s", self.address)
        await self._subscriber.connect(topics=[""])
        self.is_running = True
        self.task = asyncio.create_task(self._subscriber.listen(self._dispatch))

    async def _dispatch(self, topic: str, data: dict[str, Any]) -> None:
        symbol = data.get("symbol") if isinstance(data, dict) else None
        callbacks = list(self._global_callbacks)
        if isinstance(symbol, str) and symbol:
            # Snapshot both lists before dispatch: consumers can unregister
            # themselves without causing another same-symbol consumer to skip.
            callbacks = list(self._callbacks_by_symbol.get(symbol.upper(), ())) + callbacks

        for callback in tuple(callbacks):
            try:
                result = callback(topic, data)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                logger.exception("Error in live feed callback for topic %s", topic)

    async def stop(self) -> None:
        self.is_running = False
        if self.task is not None:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        await self._subscriber.stop()
        logger.info("LiveFeedSubscriber stopped")


# Global singleton consumer; producer ownership belongs to streamer-service.
live_feed_subscriber = LiveFeedSubscriber()
