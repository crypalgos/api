import logging
from typing import List, Optional

from crypalgos_core.engine.timeframe import timeframe_to_milliseconds

logger = logging.getLogger(__name__)

# Delta's WS stream only ever publishes 1-minute candle closes
# (execution/tick_sources.py's own docstrings) -- this is the raw
# granularity every live tick source in this app delivers today. A
# strategy declared at exactly this timeframe needs no aggregation at all
# (RuntimeFactory.build() skips constructing a CandleAggregator in that
# case) -- introducing one unconditionally would add a spurious one-tick
# delay to the 1m case that doesn't exist in the un-aggregated path today.
RAW_TICK_TIMEFRAME_MS = 60_000


class CandleAggregator:
    """Buckets raw 1-minute candle rows into a strategy's declared
    timeframe, live. Backtest and the historical seed (RuntimeFactory's
    IndicatorWarmup) both get pre-aggregated candles from ClickHouse's
    own SQL-side toStartOfInterval bucketing (crypalgos_core/database.py)
    -- there is no equivalent for a live WS feed, so this is that
    equivalent for the live tick path.

    Only ever emits a CLOSED bucket -- once a new incoming candle's
    timestamp falls into the *next* bucket, the previous one is returned;
    a still-accumulating (partial) bucket is never emitted, matching
    backtest's own "only closed bars are visible" guarantee (audit finding
    #28's whole point, generalized here to a live, sub-bar-granularity feed
    instead of a full-bar-granularity one).

    Uses the same floor-division-from-epoch bucketing ClickHouse's
    toStartOfInterval uses for every timeframe this app's UI actually
    offers (m/h/d granularities) -- consistent with the historical seed's
    own bucketing, not a second, disagreeing convention.
    """

    def __init__(self, timeframe: str) -> None:
        self.timeframe = timeframe
        self._bucket_ms = timeframe_to_milliseconds(timeframe)
        self._bucket_start: Optional[int] = None
        self._open = self._high = self._low = self._close = self._volume = 0.0

    def add_tick(self, candle_row: List[float]) -> Optional[List[float]]:
        """candle_row = [timestamp_ms, open, high, low, close, volume] from
        one raw 1-minute tick. Returns an aggregated row in the same shape
        the instant a bucket boundary is crossed, else None (still
        accumulating -- caller must not treat this as a bar to process).
        """
        ts, open_price, high, low, close, volume = candle_row
        bucket_start = (int(ts) // self._bucket_ms) * self._bucket_ms

        if self._bucket_start is None:
            self._start_bucket(bucket_start, open_price, high, low, close, volume)
            return None

        if bucket_start == self._bucket_start:
            self._high = max(self._high, high)
            self._low = min(self._low, low)
            self._close = close
            self._volume += volume
            return None

        if bucket_start < self._bucket_start:
            # Out-of-order tick (a rare WS redelivery/reconnect artifact) --
            # drop it rather than silently corrupting the current bucket
            # or rewinding time.
            logger.warning(
                "CandleAggregator(%s): dropped out-of-order tick at %d "
                "(current bucket started at %d)",
                self.timeframe, ts, self._bucket_start,
            )
            return None

        closed = [
            float(self._bucket_start), self._open, self._high,
            self._low, self._close, self._volume,
        ]
        # The market is continuous, so the new bucket's open must carry
        # forward from the bucket we just closed rather than the raw
        # incoming row's own open (which can lag the real boundary on a
        # quiet symbol) -- otherwise a gap appears between adjacent
        # persisted/broadcast bars that was never an actual price move.
        # Mirrors FormingCandle._ensure_bucket()'s identical fix for the
        # display-only candle; high/low still fold in the incoming row's
        # real range since that range did happen within the new bucket.
        continuity_price = self._close
        self._start_bucket(
            bucket_start,
            continuity_price,
            max(continuity_price, high),
            min(continuity_price, low),
            close,
            volume,
        )
        return closed

    def _start_bucket(
        self,
        bucket_start: int,
        open_price: float,
        high: float,
        low: float,
        close: float,
        volume: float,
    ) -> None:
        self._bucket_start = bucket_start
        self._open, self._high, self._low, self._close, self._volume = (
            open_price,
            high,
            low,
            close,
            volume,
        )

    def peek_partial(self) -> Optional[List[float]]:
        """Returns the current in-progress bucket's OHLCV without closing
        it -- for a live "current price" ticker only (see
        TradingRuntime.tick()'s PRICE_TICK broadcast). Never feed this into
        the closed-bar event stream: add_tick()'s "only closed bars are
        visible" guarantee must stay intact for BAR_CLOSED consumers.
        None before the first tick of a fresh bucket.
        """
        if self._bucket_start is None:
            return None
        return [
            float(self._bucket_start), self._open, self._high,
            self._low, self._close, self._volume,
        ]


class FormingCandle:
    """A mutable, display-only candle for the live viewer.

    It tracks the strategy timeframe from every ticker price and revises its
    OHLCV as Delta's active 1-minute candle arrives. It never returns a
    finalized bar and is deliberately separate from :class:`CandleAggregator`:
    the former is a UI projection, while the latter is the sole execution
    boundary for indicators, orders, persistence, and replay.
    """

    def __init__(self, timeframe: str) -> None:
        self.timeframe = timeframe
        self._bucket_ms = timeframe_to_milliseconds(timeframe)
        self._bucket_start: Optional[int] = None
        self._open = self._high = self._low = self._close = self._volume = 0.0
        self._first_price: Optional[float] = None
        self._last_price_timestamp: Optional[int] = None
        self._tick_high = float("-inf")
        self._tick_low = float("inf")
        self._minute_candles: dict[int, List[float]] = {}

    def update_price(self, timestamp: int, price: float) -> Optional[List[float]]:
        """Apply one realtime ticker price and return the current display row."""
        if price <= 0:
            return None
        if not self._ensure_bucket(timestamp, price):
            return None
        if self._last_price_timestamp is not None and timestamp < self._last_price_timestamp:
            return None

        self._last_price_timestamp = timestamp
        self._first_price = self._first_price if self._first_price is not None else price
        self._tick_high = max(self._tick_high, price)
        self._tick_low = min(self._tick_low, price)
        self._recalculate(close_override=price)
        return self.peek()

    def update_candle(self, candle_row: List[float]) -> Optional[List[float]]:
        """Apply the latest revision of one raw 1-minute Delta candle."""
        ts, open_price, high, low, close, volume = candle_row
        if not self._ensure_bucket(int(ts), float(open_price)):
            return None

        minute_start = (int(ts) // RAW_TICK_TIMEFRAME_MS) * RAW_TICK_TIMEFRAME_MS
        self._minute_candles[minute_start] = [
            float(open_price),
            float(high),
            float(low),
            float(close),
            float(volume),
        ]
        # A ticker timestamp is an actual event time, while a candle timestamp
        # is its minute's start. Preserve the newer ticker close when available.
        close_override = (
            self._close
            if self._last_price_timestamp is not None and self._last_price_timestamp > int(ts)
            else None
        )
        self._recalculate(close_override=close_override)
        return self.peek()

    def peek(self) -> Optional[List[float]]:
        if self._bucket_start is None:
            return None
        return [
            float(self._bucket_start),
            self._open,
            self._high,
            self._low,
            self._close,
            self._volume,
        ]

    def _ensure_bucket(self, timestamp: int, seed_price: float) -> bool:
        bucket_start = (int(timestamp) // self._bucket_ms) * self._bucket_ms
        if self._bucket_start is not None and bucket_start < self._bucket_start:
            return False
        if self._bucket_start != bucket_start:
            # A new candle's open must continue from the previous one's
            # close -- the market is continuous, so seeding from whatever
            # price happens to arrive first for this bucket (which can lag
            # the real boundary on a quiet symbol) drew a visible gap
            # between candles on the chart that was never an actual price
            # move. Only the very first bucket of a session (no previous
            # close to continue from) falls back to the incoming price.
            continuity_price = self._close if self._bucket_start is not None else seed_price
            self._bucket_start = bucket_start
            self._open = self._high = self._low = self._close = continuity_price
            self._volume = 0.0
            self._first_price = continuity_price
            self._last_price_timestamp = None
            self._tick_high = continuity_price
            self._tick_low = continuity_price
            self._minute_candles = {}
        return True

    def _recalculate(self, close_override: Optional[float]) -> None:
        ordered = sorted(self._minute_candles.items())
        if ordered:
            first = ordered[0][1]
            self._open = first[0]
            raw_high = max(row[1] for _, row in ordered)
            raw_low = min(row[2] for _, row in ordered)
            raw_close = ordered[-1][1][3]
            self._volume = sum(row[4] for _, row in ordered)
        else:
            seed = self._first_price if self._first_price is not None else self._close
            self._open = seed
            raw_high = raw_low = raw_close = seed
            self._volume = 0.0

        self._high = max(raw_high, self._tick_high)
        self._low = min(raw_low, self._tick_low)
        self._close = close_override if close_override is not None else raw_close
