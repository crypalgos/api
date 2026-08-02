"""Unit tests for CandleAggregator — buckets raw 1-minute candle rows into
a strategy's declared timeframe for the live tick path (backtest/the
historical seed both get this from ClickHouse's own SQL-side
toStartOfInterval bucketing; there is no live equivalent otherwise).
"""

from app.modules.strategy_service.execution.candle_aggregator import (
    RAW_TICK_TIMEFRAME_MS,
    CandleAggregator,
    FormingCandle,
)

ONE_MIN = 60_000
FIVE_MIN = 5 * ONE_MIN


def _tick(ts_ms: int, o: float, h: float, l: float, c: float, v: float):
    return [float(ts_ms), o, h, l, c, v]


def test_no_emission_until_a_bucket_boundary_is_crossed():
    agg = CandleAggregator("5m")
    assert agg.add_tick(_tick(0, 100, 101, 99, 100, 10)) is None
    assert agg.add_tick(_tick(ONE_MIN, 100, 105, 99, 102, 10)) is None
    assert agg.add_tick(_tick(2 * ONE_MIN, 102, 103, 98, 99, 10)) is None
    assert agg.add_tick(_tick(3 * ONE_MIN, 99, 100, 95, 97, 10)) is None
    assert agg.add_tick(_tick(4 * ONE_MIN, 97, 99, 96, 98, 10)) is None


def test_bucket_closes_with_correctly_aggregated_ohlcv():
    agg = CandleAggregator("5m")
    # Five 1-minute ticks inside bucket [0, 5min).
    for i, (o, h, l, c) in enumerate(
        [(100, 101, 99, 100), (100, 105, 99, 102), (102, 103, 98, 99), (99, 100, 95, 97), (97, 99, 96, 98)]
    ):
        result = agg.add_tick(_tick(i * ONE_MIN, o, h, l, c, 10))
        assert result is None, f"tick {i} should not close the bucket yet"

    # First tick of the NEXT bucket closes the previous one.
    closed = agg.add_tick(_tick(FIVE_MIN, 98, 99, 97, 98, 10))
    assert closed is not None
    ts, o, h, l, c, v = closed
    assert ts == 0.0  # bucket's own timestamp is its OPEN time
    assert o == 100.0  # first tick's open
    assert h == 105.0  # max high across all 5 ticks
    assert l == 95.0   # min low across all 5 ticks
    assert c == 98.0   # last tick's close (tick index 4)
    assert v == 50.0   # sum of volumes (5 * 10)


def test_multiple_consecutive_boundaries_each_emit_exactly_one_closed_bucket():
    agg = CandleAggregator("5m")
    closes = []
    # 15 minutes of ticks -> 3 closed 5-minute buckets expected (the 3rd
    # bucket's own close only happens once a tick from bucket 4 arrives).
    for i in range(16):
        result = agg.add_tick(_tick(i * ONE_MIN, 100 + i, 100 + i, 100 + i, 100 + i, 1))
        if result is not None:
            closes.append(result)
    assert len(closes) == 3
    assert [c[0] for c in closes] == [0.0, float(FIVE_MIN), float(2 * FIVE_MIN)]


def test_out_of_order_tick_is_dropped_not_corrupting_the_current_bucket():
    agg = CandleAggregator("5m")
    # Bucket 1: [0, 5min). Bucket 2: [5min, 10min) -- opened by the tick below.
    agg.add_tick(_tick(0, 100, 101, 99, 100, 10))
    agg.add_tick(_tick(FIVE_MIN, 100, 101, 99, 100, 10))  # closes bucket 1, opens bucket 2
    # A stale tick belonging to the ALREADY-CLOSED bucket 1 arrives late
    # (e.g. a WS redelivery) -- must be dropped, not treated as closing
    # bucket 2 early or rewinding bucket 2's accumulated high/low.
    result = agg.add_tick(_tick(ONE_MIN, 200, 300, 1, 250, 999))
    assert result is None
    # Bucket 2's own state must be unaffected by the dropped stale tick.
    closed = agg.add_tick(_tick(2 * FIVE_MIN, 100, 100, 100, 100, 1))
    assert closed is not None
    assert closed[2] == 101.0  # high -- NOT 300 from the dropped stale tick
    assert closed[3] == 99.0   # low -- NOT 1 from the dropped stale tick


def test_candle_aggregator_new_bucket_opens_at_previous_bucket_close():
    """Same continuity guarantee as FormingCandle, but for the persisted/
    broadcast BAR_CLOSED bar: a new bucket's open must carry forward from
    the bucket just closed, not from whatever the raw incoming row's own
    open happens to say (which can lag the real boundary on a quiet
    symbol) -- otherwise adjacent bars show a gap that was never a real
    price move."""
    agg = CandleAggregator("5m")
    agg.add_tick(_tick(0, 100, 101, 99, 105, 10))  # bucket 1 closes at 105

    # First tick of bucket 2 claims a raw open of 250 -- far from 105.
    # This call closes bucket 1 (returned as `closed`, unaffected by the
    # continuity fix) and seeds bucket 2 from bucket 1's close instead.
    closed = agg.add_tick(_tick(FIVE_MIN, 250, 260, 240, 255, 10))
    assert closed is not None
    assert closed[1] == 100.0  # bucket 1's own open, untouched by the fix

    # Bucket 2 itself must reflect continuity, not the raw 250 open.
    final = agg.add_tick(_tick(2 * FIVE_MIN, 255, 255, 255, 255, 1))
    assert final is not None
    _, open_, high, low, close, _ = final
    assert open_ == 105.0  # continuity price
    assert high == 260.0   # real incoming high still captured
    assert low == 105.0    # continuity price extends the low since 105 < 240
    assert close == 255.0  # real incoming close unaffected


def test_raw_tick_timeframe_matches_one_minute():
    """RuntimeFactory.build() skips constructing an aggregator entirely
    when the strategy's declared timeframe already equals this -- a
    regression here would silently reintroduce either a spurious
    aggregation delay or a skipped one."""
    assert RAW_TICK_TIMEFRAME_MS == ONE_MIN


def test_forming_candle_new_bucket_opens_at_previous_bucket_close():
    """A new candle's open must continue from the previous one's close --
    the underlying market is continuous. Seeding the new bucket from
    whatever price happens to arrive first (rather than from where the
    prior candle actually closed) drew a visible, artificial gap on the
    live chart that was never a real price move."""
    candle = FormingCandle("1m")
    candle.update_price(0, 100.0)
    candle.update_price(30_000, 105.0)  # still bucket 1; close moves to 105.0

    row = candle.update_price(ONE_MIN, 250.0)  # first tick of bucket 2
    assert row is not None
    _, open_, high, low, close, _ = row
    assert open_ == 105.0  # bucket 1's close, NOT the raw 250.0 tick
    assert close == 250.0  # the real incoming price is still reflected
    assert high == 250.0
    assert low == 105.0


def test_forming_candle_first_bucket_ever_falls_back_to_seed_price():
    """No previous bucket exists yet on the very first tick of a session --
    there is nothing to continue from, so the seed price is used as-is."""
    candle = FormingCandle("1m")
    row = candle.update_price(0, 100.0)
    assert row is not None
    assert row[1] == 100.0  # open == seed price
