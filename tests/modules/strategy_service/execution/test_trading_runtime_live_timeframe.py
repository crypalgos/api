"""End-to-end integration test for TradingRuntime.tick() with a strategy
declared at a coarser timeframe than the raw 1-minute tick granularity
Delta's WS feed actually delivers.

Two real bugs were found and fixed together during Phase 3 end-to-end
verification, both invisible in isolation:
  1. Indicators started with a completely empty buffer -- every live bar
     crashed with IndexError (see indicator_warmup.py).
  2. A "1h" strategy got on_event() called once per real *minute* (Delta's
     WS stream is 1-minute-only), with indicators seeded from hourly
     history but fed minute-by-minute live appends -- silently corrupting
     them (see candle_aggregator.py).

This test drives real TradingRuntime.tick() (not a mock) with synthetic
1-minute ticks spanning several hours, against a real EMA indicator and a
real PaperBroker, using no DB/Redis/ClickHouse/network -- the same
zero-infra bar this package's other tests hold themselves to.
"""

import asyncio
from dataclasses import dataclass
from typing import Any, List

from crypalgos_core.engine.context import ExecutionContext, ExecutionMode
from crypalgos_core.engine.risk_engine import RiskEngine
from crypalgos_core.engine.strategy_base import StrategyBase
from crypalgos_core.events import Event, EventType
from crypalgos_core.indicators import Indicator

from app.modules.strategy_service.execution.candle_aggregator import CandleAggregator
from app.modules.strategy_service.execution.indicator_warmup import (
    IndicatorWarmup,
    discover_indicators,
)
from app.modules.strategy_service.execution.trading_runtime import TradingRuntime
from app.modules.strategy_service.models.live_trading_session_model import (
    SessionEnvironment,
)
from app.modules.strategy_service.paper_broker import PaperBroker

ONE_MIN_MS = 60_000
ONE_HOUR_MS = 60 * ONE_MIN_MS


class HourlyEMAStrategy(StrategyBase):
    """Mirrors the real compiled-strategy shape found live: an indicator
    set as a plain instance attribute in initialize(), read via
    `.value[0]`/`.value[1]` from on_event() -- exactly what crashed with
    IndexError against an unseeded buffer."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.observed_bars: List[list] = []
        self.ema_values_seen: List[float] = []

    def initialize(self) -> None:
        self.ema = Indicator.EMA(period=3).bind("btcusd", timeframe="1h")

    def on_event(self, event: Event) -> None:
        self.observed_bars.append(event.data["candle"])
        # This is exactly the access pattern that crashed with
        # "IndexError: Index offset 0 out of bounds for SeriesBuffer of
        # length 0" before indicator_warmup.py existed.
        self.ema_values_seen.append(self.ema.value[0])


def _synthetic_hourly_history(num_hours: int, start_ts_ms: int, start_price: float):
    """A plausible-looking historical candle array in the exact shape
    load_candles_from_clickhouse returns, standing in for a real ClickHouse
    fetch (RuntimeFactory._seed_indicators's job in production)."""
    import numpy as np

    rows = []
    price = start_price
    for i in range(num_hours):
        ts = start_ts_ms - (num_hours - i) * ONE_HOUR_MS
        rows.append([float(ts), price, price + 1, price - 1, price, 100.0])
        price += 1
    return np.array(rows)


def _minute_tick(ts_ms: int, price: float) -> Event:
    return Event(
        type=EventType.BAR,
        timestamp=ts_ms,
        symbol="BTCUSD",
        data={"candle": [float(ts_ms), price, price + 0.5, price - 0.5, price, 1.0]},
    )


async def test_hourly_strategy_only_runs_on_the_hour_with_correctly_aggregated_bars_and_seeded_indicators():
    strategy = HourlyEMAStrategy(initial_capital=10_000.0, leverage=1, run_id="test-run")
    strategy.initialize()

    session_start_ts = 10 * ONE_HOUR_MS  # arbitrary epoch-aligned hour boundary
    history = _synthetic_hourly_history(10, session_start_ts, start_price=100.0)

    indicators = discover_indicators(strategy)
    assert len(indicators) == 1, "test setup sanity check: exactly one EMA indicator"
    warmup = IndicatorWarmup(indicators)
    warmup.seed(history)
    # Seeding alone must already satisfy .value[0]/.value[1] -- this is
    # exactly what a genuine first live bar needs immediately.
    assert strategy.ema.warmup_complete()

    runtime = TradingRuntime(
        strategy=strategy,
        broker=PaperBroker(initial_capital=10_000.0),
        risk_engine=RiskEngine(max_leverage=1.0),
        context=ExecutionContext(
            strategy_run_id="test-run", user_id="test-user", mode=ExecutionMode.PAPER
        ),
        timeframe="1h",
        symbol="BTCUSD",
        indicator_warmup=warmup,
        candle_aggregator=CandleAggregator("1h"),
    )

    # Feed 3 hours' worth of 1-minute ticks (Delta's actual WS granularity).
    total_events = 0
    for minute in range(3 * 60):
        ts = session_start_ts + minute * ONE_MIN_MS
        price = 110.0 + minute * 0.01
        events = await runtime.tick(_minute_tick(ts, price))
        total_events += len(events)
        # No exception anywhere in this loop is itself half the point --
        # this is exactly where the pre-fix code crashed on bar 1.

    # Exactly 2 bucket closes in a 180-minute (3-hour) run: the boundary at
    # +60min and +120min. The 3rd hour's own bucket is still open when the
    # loop ends (never closed, since no tick from hour 4 ever arrived) --
    # matching CandleAggregator's "only emit once genuinely closed" contract.
    assert len(strategy.observed_bars) == 2
    assert strategy.observed_bars[0][0] == float(session_start_ts)
    assert strategy.observed_bars[1][0] == float(session_start_ts + ONE_HOUR_MS)

    # Each observed bar must be the real OHLCV aggregate of its 60
    # underlying 1-minute ticks, not a single raw minute's candle.
    first_bar = strategy.observed_bars[0]
    first_hour_prices = [110.0 + m * 0.01 for m in range(60)]
    assert first_bar[1] == first_hour_prices[0]   # open = first tick's own open
    assert first_bar[4] == first_hour_prices[-1]  # close = last tick's own close

    # The indicator must have been fed exactly the 2 aggregated hourly
    # closes, not all 180 raw one-minute prices -- proving on_new_bar()
    # only ever receives closed buckets, never partial ones.
    assert len(strategy.ema_values_seen) == 2


class _DisplayOnlyPublisher:
    def __init__(self) -> None:
        self.raw_messages: List[dict] = []

    async def broadcast_raw(self, message: dict) -> None:
        self.raw_messages.append(message)


async def test_ticker_event_only_broadcasts_mutable_price_and_never_executes_strategy():
    """PRICE_TICK updates the live chart, while a finalized BAR still reaches
    TickEngine. This is the common provider contract for Testnet and Mainnet."""
    from unittest.mock import AsyncMock

    strategy = HourlyEMAStrategy(initial_capital=10_000.0, leverage=1, run_id="display-run")
    strategy.initialize()
    runtime = TradingRuntime(
        strategy=strategy,
        broker=PaperBroker(initial_capital=10_000.0),
        risk_engine=RiskEngine(max_leverage=1.0),
        context=ExecutionContext(
            strategy_run_id="display-run", user_id="test-user", mode=ExecutionMode.PAPER
        ),
        timeframe="1m",
        symbol="BTCUSD",
    )
    publisher = _DisplayOnlyPublisher()
    runtime.event_publisher = publisher  # type: ignore[assignment]
    process_bar = AsyncMock(return_value=[])
    runtime.tick_engine.process_bar = process_bar

    timestamp = 1_700_000_000_000
    assert await runtime.tick(
        Event(
            type=EventType.BAR,
            timestamp=timestamp,
            symbol="BTCUSD",
            data={"ticker": {"price": 100.0}},
        )
    ) == []
    process_bar.assert_not_awaited()
    assert publisher.raw_messages == [
        {
            "type": "PRICE_TICK",
            "sequence_number": 0,
            "timestamp": timestamp - timestamp % ONE_MIN_MS,
            "source_timestamp": timestamp,
            "payload": {
                "symbol": "BTCUSD",
                "open": 100.0,
                "high": 100.0,
                "low": 100.0,
                "close": 100.0,
                "volume": 0.0,
            },
        }
    ]

    await runtime.tick(
        Event(
            type=EventType.BAR,
            timestamp=timestamp,
            symbol="BTCUSD",
            data={
                "candle": [timestamp, 100.0, 101.0, 99.0, 100.5, 1.0],
                "is_closed": True,
            },
        )
    )
    process_bar.assert_awaited_once()


@dataclass
class _FakeOfficialCandle:
    timestamp_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float


class _FakeMarketDataAdapter:
    """Stands in for DeltaMarketDataAdapter without any real HTTP call --
    TradingRuntime only ever calls fetch_ohlcv(symbol, timeframe, since_ms,
    limit), so that's the entire surface this needs to satisfy."""

    def __init__(self, candles: List[_FakeOfficialCandle], delay: float = 0.0) -> None:
        self._candles = candles
        self._delay = delay
        self.calls: List[dict] = []

    async def fetch_ohlcv(self, symbol: str, timeframe: str, since_ms: int, limit: int):
        self.calls.append(
            {"symbol": symbol, "timeframe": timeframe, "since_ms": since_ms, "limit": limit}
        )
        if self._delay:
            await asyncio.sleep(self._delay)
        return self._candles


def _build_hourly_runtime(strategy: HourlyEMAStrategy, **kwargs: Any) -> TradingRuntime:
    return TradingRuntime(
        strategy=strategy,
        broker=PaperBroker(initial_capital=10_000.0),
        risk_engine=RiskEngine(max_leverage=1.0),
        context=ExecutionContext(
            strategy_run_id="reconcile-run", user_id="test-user", mode=ExecutionMode.PAPER
        ),
        timeframe="1h",
        symbol="BTCUSD",
        candle_aggregator=CandleAggregator("1h"),
        **kwargs,
    )


async def _feed_one_hour(runtime: TradingRuntime, start_ts: int, start_price: float) -> None:
    # CandleAggregator only emits a bucket once a tick from the *next*
    # bucket proves it closed (see its own "only closed bars are visible"
    # contract) -- 61 ticks, not 60, are needed to close exactly one hour.
    for minute in range(61):
        ts = start_ts + minute * ONE_MIN_MS
        price = start_price + minute * 0.01
        await runtime.tick(_minute_tick(ts, price))


async def test_reconcile_swaps_in_deltas_official_candle_for_testnet():
    """A locally-aggregated bucket close must be replaced by Delta's own
    finalized candle for that exact window before it ever reaches the
    strategy -- otherwise the trader's execution and CrypAlgos' own replay
    would each show a different "true" close for the same bar."""
    strategy = HourlyEMAStrategy(initial_capital=10_000.0, leverage=1, run_id="reconcile-run")
    strategy.initialize()

    session_start_ts = 10 * ONE_HOUR_MS
    official = _FakeOfficialCandle(
        timestamp_ms=session_start_ts, open=111.0, high=222.0, low=90.0, close=200.0, volume=999.0
    )
    adapter = _FakeMarketDataAdapter([official])
    runtime = _build_hourly_runtime(
        strategy,
        environment=SessionEnvironment.TESTNET,
        market_data_adapter=adapter,
    )

    await _feed_one_hour(runtime, session_start_ts, start_price=110.0)

    assert len(strategy.observed_bars) == 1
    observed = strategy.observed_bars[0]
    # Delta's official values, not the locally-rolled-up 1-minute aggregate
    # (open=110.0, close=110.59, high/low/volume derived from the raw ticks).
    assert observed == [
        float(session_start_ts), 111.0, 222.0, 90.0, 200.0, 999.0,
    ]
    assert adapter.calls == [
        {"symbol": "BTCUSD", "timeframe": "1h", "since_ms": session_start_ts, "limit": 2}
    ]


async def test_reconcile_falls_back_to_local_aggregate_when_delta_has_no_match():
    """Delta not yet having published the bucket (empty result, or a result
    for a different window) must never crash or stall the session -- the
    locally-aggregated candle is used, unchanged."""
    strategy = HourlyEMAStrategy(initial_capital=10_000.0, leverage=1, run_id="reconcile-run")
    strategy.initialize()

    session_start_ts = 10 * ONE_HOUR_MS
    adapter = _FakeMarketDataAdapter([])  # Delta hasn't published this bucket yet
    runtime = _build_hourly_runtime(
        strategy,
        environment=SessionEnvironment.TESTNET,
        market_data_adapter=adapter,
    )

    await _feed_one_hour(runtime, session_start_ts, start_price=110.0)

    assert len(strategy.observed_bars) == 1
    observed = strategy.observed_bars[0]
    assert observed[0] == float(session_start_ts)
    assert observed[1] == 110.0  # local open, unchanged by a failed reconciliation
    assert observed[4] == 110.0 + 59 * 0.01  # local close, unchanged


async def test_reconcile_skipped_for_non_testnet_sessions():
    """PRODUCTION sessions already source finalized bars from ClickHouse
    (see _fetch_warmup_candles) -- live reconciliation against Delta's REST
    API is TESTNET-only and must never fire, adapter or not."""
    strategy = HourlyEMAStrategy(initial_capital=10_000.0, leverage=1, run_id="reconcile-run")
    strategy.initialize()

    session_start_ts = 10 * ONE_HOUR_MS
    adapter = _FakeMarketDataAdapter(
        [_FakeOfficialCandle(session_start_ts, 111.0, 222.0, 90.0, 200.0, 999.0)]
    )
    runtime = _build_hourly_runtime(
        strategy,
        environment=SessionEnvironment.PRODUCTION,
        market_data_adapter=adapter,
    )

    await _feed_one_hour(runtime, session_start_ts, start_price=110.0)

    assert adapter.calls == []
    assert strategy.observed_bars[0][1] == 110.0  # local aggregate, not Delta's official value
