"""Focused contract tests for the shared Mainnet live-data provider."""

from app.modules.strategy_service.execution.tick_sources import (
    DeltaMainnetTickSource,
    parse_ohlcv_tick,
    parse_price_tick,
)


def test_real_publisher_ohlcv_topic_format_is_recognized():
    event = parse_ohlcv_tick(
        "ohlcv.delta",
        {
            "exchange": "delta",
            "symbol": "BTCUSD",
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "volume": 12.0,
            "timestamp": 1_700_000_000_000,
        },
    )
    assert event is not None
    assert event.symbol == "BTCUSD"
    assert event.timestamp == 1_700_000_000_000
    assert event.data["candle"] == [
        1_700_000_000_000,
        100.0,
        101.0,
        99.0,
        100.5,
        12.0,
    ]


def test_non_ohlcv_topics_are_ignored_by_candle_parser():
    assert parse_ohlcv_tick("trades.delta", {"symbol": "BTCUSD"}) is None
    assert parse_ohlcv_tick("ticker.delta", {"symbol": "BTCUSD"}) is None


def test_missing_or_malformed_ohlcv_is_ignored_not_crashed():
    assert parse_ohlcv_tick("ohlcv.delta", {"open": 1.0}) is None
    assert parse_ohlcv_tick(
        "ohlcv.delta", {"symbol": "BTCUSD", "timestamp": 1, "open": "bad"}
    ) is None


def test_trade_and_ticker_parser_use_executable_last_price_only():
    trade = parse_price_tick(
        "trades.delta",
        {"symbol": "BTCUSD", "price": 101.5, "timestamp": 1_700_000_000_000},
    )
    ticker = parse_price_tick(
        "ticker.delta",
        {
            "symbol": "BTCUSD",
            "last": 102.5,
            "mark_price": 99.0,
            "timestamp": 1_700_000_000_001,
        },
    )
    assert trade is not None
    assert trade.data == {"ticker": {"price": 101.5}}
    assert ticker is not None
    assert ticker.data == {"ticker": {"price": 102.5}}
    assert parse_price_tick(
        "ticker.delta",
        {"symbol": "BTCUSD", "mark_price": 99.0, "timestamp": 1},
    ) is None


async def test_mainnet_coalesces_plural_trade_and_ticker_updates_to_latest_display_price():
    source = DeltaMainnetTickSource("BTCUSD")
    await source._on_tick(
        "trades.delta",
        {"symbol": "BTCUSD", "price": 100.0, "timestamp": 1_700_000_000_000},
    )
    await source._on_tick(
        "ticker.delta",
        {"symbol": "BTCUSD", "last": 101.0, "timestamp": 1_700_000_000_001},
    )

    event = await source.next_bar(timeout=0.01)
    assert event is not None
    assert event.data == {"ticker": {"price": 101.0}}
    assert event.timestamp == 1_700_000_000_001


async def test_mainnet_ignores_malformed_and_other_symbol_price_updates():
    source = DeltaMainnetTickSource("BTCUSD")
    await source._on_tick(
        "trades.delta",
        {"symbol": "BTCUSD", "price": "bad", "timestamp": 1},
    )
    await source._on_tick(
        "ticker.delta",
        {"symbol": "ETHUSD", "last": 101.0, "timestamp": 2},
    )
    assert await source.next_bar(timeout=0.01) is None


async def test_mainnet_returns_closed_previous_candle_before_new_forming_candle():
    source = DeltaMainnetTickSource("BTCUSD")
    first = {
        "symbol": "BTCUSD",
        "open": 100.0,
        "high": 101.0,
        "low": 99.0,
        "close": 100.5,
        "volume": 1.0,
        "timestamp": 60_000,
    }
    second = {**first, "timestamp": 120_000, "close": 102.0}

    await source._on_tick("ohlcv.delta", first)
    initial_forming = await source.next_bar(timeout=0.01)
    assert initial_forming is not None
    assert initial_forming.data["is_closed"] is False

    await source._on_tick("ohlcv.delta", second)
    closed = await source.next_bar(timeout=0.01)
    new_forming = await source.next_bar(timeout=0.01)

    assert closed is not None
    assert closed.timestamp == 60_000
    assert closed.data["is_closed"] is True
    assert new_forming is not None
    assert new_forming.timestamp == 120_000
    assert new_forming.data["is_closed"] is False
