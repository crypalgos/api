import asyncio
import logging
from typing import Any, Dict, Optional, Protocol

from crypalgos_core.events import Event, EventType

logger = logging.getLogger(__name__)


class LiveMarketDataProvider(Protocol):
    """Environment-neutral live-market contract consumed by LiveTradingRunner."""

    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    async def next_bar(self, timeout: Optional[float] = None) -> Optional[Event]: ...


def parse_ohlcv_tick(topic: str, data: Dict[str, Any]) -> Optional[Event]:
    """Convert a shared-feed 1-minute Delta candle into a raw BAR event."""
    if not topic.startswith("ohlcv") or not isinstance(data, dict):
        return None
    symbol = data.get("symbol")
    timestamp = data.get("timestamp")
    if not symbol or timestamp is None:
        return None
    try:
        candle_arr = [
            int(timestamp),
            float(data["open"]),
            float(data["high"]),
            float(data["low"]),
            float(data["close"]),
            float(data["volume"]),
        ]
    except (KeyError, TypeError, ValueError):
        return None
    return Event(
        type=EventType.BAR,
        timestamp=candle_arr[0],
        symbol=symbol,
        data={"candle": candle_arr},
    )


def parse_price_tick(topic: str, data: Dict[str, Any]) -> Optional[Event]:
    """Convert a shared Delta trade/ticker update into a display-only event.

    The data client normalizes exchange timestamps to milliseconds before the
    message reaches this boundary. A ticker never falls back to ``mark_price``:
    the live chart must retain the same traded/executable price basis as orders.
    """
    is_trade = topic.startswith(("trade.", "trades."))
    if not (is_trade or topic.startswith("ticker.")) or not isinstance(data, dict):
        return None
    try:
        symbol = data["symbol"]
        price = float(data["price"] if is_trade else data["last"])
        timestamp = int(data["timestamp"])
    except (KeyError, TypeError, ValueError):
        return None
    if not symbol or price <= 0 or timestamp <= 0:
        return None
    return Event(
        type=EventType.BAR,
        timestamp=timestamp,
        symbol=symbol,
        data={"ticker": {"price": price}},
    )


def _with_finality(event: Event, is_closed: bool) -> Event:
    return Event(
        type=event.type,
        timestamp=event.timestamp,
        symbol=event.symbol,
        data={**event.data, "is_closed": is_closed},
    )


class _QueueBroker:
    """Per-session handoff with lossless candles and latest-only display ticks.

    Delta can emit many trades while the renderer only needs the newest price.
    Retaining every one creates a stale queue that visibly lags the exchange.
    Candle updates remain lossless because they establish the finalized-bar
    boundary used by execution.
    """

    def __init__(self) -> None:
        self.queue: "asyncio.Queue[tuple[str, Any]]" = asyncio.Queue()
        self._latest_display_update: Optional[tuple[str, Any]] = None
        self._display_update_available = asyncio.Event()

    async def publish(self, topic: str, data: Any) -> None:
        if topic.startswith(("trade.", "trades.", "ticker.")):
            self._latest_display_update = (topic, data)
            self._display_update_available.set()
            return
        await self.queue.put((topic, data))

    def _take_latest_display_update(self) -> Optional[tuple[str, Any]]:
        update = self._latest_display_update
        self._latest_display_update = None
        self._display_update_available.clear()
        return update

    async def next_update(
        self, timeout: Optional[float]
    ) -> Optional[tuple[str, Any]]:
        """Return a reliable candle first, otherwise the newest display tick."""
        try:
            return self.queue.get_nowait()
        except asyncio.QueueEmpty:
            pass

        if (update := self._take_latest_display_update()) is not None:
            return update

        candle_task = asyncio.create_task(self.queue.get())
        display_task = asyncio.create_task(self._display_update_available.wait())
        done, pending = await asyncio.wait(
            {candle_task, display_task},
            timeout=timeout,
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        if not done:
            return None

        # Execution boundaries win if both arrive together; the latest display
        # price remains stored for the next loop rather than being discarded.
        if candle_task in done:
            return candle_task.result()
        return self._take_latest_display_update()


class DeltaTestnetTickSource:
    """Direct Testnet WebSocket provider for one session's Delta symbol."""

    def __init__(
        self, symbol: str, api_key: str = "", api_secret: str = ""
    ) -> None:
        from crypalgos_data.stream.exchanges.delta import DeltaExchangeClient

        self.symbol = symbol
        self._broker = _QueueBroker()
        self._client = DeltaExchangeClient(
            self._broker,
            symbols=[symbol],
            api_key=api_key or None,
            api_secret=api_secret or None,
            testnet=True,
        )
        self._task: Optional[asyncio.Task] = None
        self._messages_seen = 0
        self._symbol_mismatches = 0
        self._forming_event: Optional[Event] = None
        self._ready_events: "asyncio.Queue[Event]" = asyncio.Queue()

    async def start(self) -> None:
        self._task = asyncio.create_task(self._client.connect())
        logger.info("DeltaTestnetTickSource started for %s", self.symbol)

    async def stop(self) -> None:
        await self._client.stop()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def next_bar(self, timeout: Optional[float] = None) -> Optional[Event]:
        """Return a final/forming candle or a broadcast-only Testnet ticker update."""
        try:
            return self._ready_events.get_nowait()
        except asyncio.QueueEmpty:
            pass

        while True:
            update = await self._broker.next_update(timeout)
            if update is None:
                if self._messages_seen == 0:
                    logger.warning(
                        "DeltaTestnetTickSource(%s): no WS messages received yet; "
                        "the Testnet feed may be disconnected or silent.",
                        self.symbol,
                    )
                return None

            topic, data = update
            self._messages_seen += 1
            if topic.startswith(("trade", "ticker")):
                if getattr(data, "symbol", None) != self.symbol:
                    continue
                price = float(
                    getattr(data, "price", 0)
                    if topic.startswith("trade")
                    else getattr(data, "last", 0)
                )
                timestamp = int(getattr(data, "timestamp", 0))
                if price <= 0 or timestamp <= 0:
                    continue
                return Event(
                    type=EventType.BAR,
                    timestamp=timestamp,
                    symbol=self.symbol,
                    data={"ticker": {"price": price}},
                )

            if not topic.startswith("ohlcv"):
                continue
            candle = data
            if candle.symbol != self.symbol:
                self._symbol_mismatches += 1
                if self._symbol_mismatches in (1, 10, 50) or self._symbol_mismatches % 200 == 0:
                    logger.warning(
                        "DeltaTestnetTickSource(%s): received candle for different "
                        "symbol %r (%d times)",
                        self.symbol,
                        candle.symbol,
                        self._symbol_mismatches,
                    )
                continue

            event = Event(
                type=EventType.BAR,
                timestamp=candle.timestamp_ms,
                symbol=candle.symbol,
                data={
                    "candle": [
                        candle.timestamp_ms,
                        candle.open,
                        candle.high,
                        candle.low,
                        candle.close,
                        candle.volume,
                    ]
                },
            )
            if self._forming_event is not None and event.timestamp < self._forming_event.timestamp:
                logger.warning(
                    "DeltaTestnetTickSource(%s): dropped out-of-order candle ts=%s",
                    self.symbol,
                    event.timestamp,
                )
                continue
            if self._forming_event is not None and event.timestamp > self._forming_event.timestamp:
                closed = _with_finality(self._forming_event, True)
                self._forming_event = event
                await self._ready_events.put(_with_finality(event, False))
                logger.info(
                    "DeltaTestnetTickSource(%s): bar closed close=%s ts=%s",
                    self.symbol,
                    closed.data["candle"][4],
                    closed.timestamp,
                )
                return closed

            self._forming_event = event
            return _with_finality(event, False)


class DeltaMainnetTickSource:
    """Shared-mainnet provider with the same event contract as Testnet.

    ``StreamerManager`` owns one Delta Mainnet WebSocket and fans out normalized
    trades, ticker updates, and 1-minute candle revisions via ZMQ. This source
    converts those messages into display-only price ticks and ordered forming /
    finalized candles; ``TradingRuntime`` remains environment-neutral.
    """

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        self._broker = _QueueBroker()
        self._messages_seen = 0
        self._symbol_mismatches = 0
        self._forming_event: Optional[Event] = None

    def _is_target_symbol(self, event: Event, kind: str) -> bool:
        if event.symbol == self.symbol:
            return True
        self._symbol_mismatches += 1
        if self._symbol_mismatches in (1, 10, 50) or self._symbol_mismatches % 200 == 0:
            logger.warning(
                "DeltaMainnetTickSource(%s): received %s for different symbol %r "
                "(%d times)",
                self.symbol,
                kind,
                event.symbol,
                self._symbol_mismatches,
            )
        return False

    async def _on_tick(self, topic: str, data: Any) -> None:
        self._messages_seen += 1

        price_event = parse_price_tick(topic, data)
        if price_event is not None:
            if self._is_target_symbol(price_event, "price update"):
                await self._broker.publish(topic, price_event)
            return

        event = parse_ohlcv_tick(topic, data)
        if event is None or not self._is_target_symbol(event, "ohlcv"):
            return
        if self._forming_event is not None and event.timestamp < self._forming_event.timestamp:
            logger.warning(
                "DeltaMainnetTickSource(%s): dropped out-of-order candle ts=%s "
                "(current forming ts=%s)",
                self.symbol,
                event.timestamp,
                self._forming_event.timestamp,
            )
            return

        if self._forming_event is not None and event.timestamp > self._forming_event.timestamp:
            # Keep the final previous bar ahead of the new mutable bar. The
            # reliable FIFO preserves this exact ordering even under trade load.
            await self._broker.publish("ohlcv.delta", _with_finality(self._forming_event, True))
            logger.info(
                "DeltaMainnetTickSource(%s): bar closed ts=%s",
                self.symbol,
                self._forming_event.timestamp,
            )

        self._forming_event = event
        await self._broker.publish("ohlcv.delta", _with_finality(event, False))

    async def start(self) -> None:
        from app.modules.data_service.live_feed import live_feed_subscriber

        live_feed_subscriber.register_callback(self.symbol, self._on_tick)
        await live_feed_subscriber.start()
        logger.info("DeltaMainnetTickSource started for %s", self.symbol)

    async def stop(self) -> None:
        from app.modules.data_service.live_feed import live_feed_subscriber

        live_feed_subscriber.unregister_callback(self.symbol, self._on_tick)

    async def next_bar(self, timeout: Optional[float] = None) -> Optional[Event]:
        update = await self._broker.next_update(timeout)
        if update is not None:
            _, event = update
            return event
        if self._messages_seen == 0:
            logger.warning(
                "DeltaMainnetTickSource(%s): no messages from the shared feed yet; "
                "check StreamerManager/live_feed_subscriber.",
                self.symbol,
            )
        return None
