"""Regression tests for warmup-candle seeding.

Historical candles fetched for indicator warmup never flowed through
TickEngine.process_bar() (only live ticks do), so the event stream -- and
any chart built from it -- had zero OHLCV data until the first genuinely
new live bar closed. For a coarse-timeframe strategy that can take a full
timeframe period, and was the direct cause of a live/paper session showing
"0 bars" in the UI immediately after starting.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import numpy as np

from crypalgos_core.engine.context import ExecutionContext, ExecutionMode
from crypalgos_core.events.engine_events import BarClosedEvent

from app.modules.strategy_service.execution import event_publisher as pub_mod
from app.modules.strategy_service.execution.trading_runtime import RuntimeFactory
from app.modules.strategy_service.models.live_trading_session_model import (
    SessionEnvironment,
)

COMPILED_CODE = """
from crypalgos_core.engine.strategy_base import StrategyBase

class _T(StrategyBase):
    exchange = "delta"
    datasources = {"btcusd": {"symbol": "BTCUSD", "leverage": 1, "timeframes": ["1m"]}}
    def initialize(self): pass
    def on_event(self, event): pass
"""


def _candles(n: int, start_ts: int = 1_700_000_000_000) -> np.ndarray:
    rows = []
    for i in range(n):
        ts = start_ts + i * 60_000
        price = 100.0 + i
        rows.append([ts, price, price + 1, price - 1, price, 10.0])
    return np.array(rows)


def test_build_warmup_bar_events_produces_correct_ohlcv_and_negative_indices() -> None:
    candles = _candles(3)
    context = ExecutionContext(
        strategy_run_id="run-1", user_id="user-1", mode=ExecutionMode.PAPER
    )

    events = RuntimeFactory._build_warmup_bar_events(candles, "BTCUSD", "1m", context)

    assert len(events) == 3
    assert all(isinstance(e, BarClosedEvent) for e in events)
    # Oldest first, numbered -3, -2, -1 -- strictly before TickEngine's own
    # 0-based positive numbering for the first live bar of this same session,
    # so merging the two never collides and chronological order holds.
    assert [e.sequence_number for e in events] == [-3, -2, -1]
    assert [e.candle_index for e in events] == [-3, -2, -1]
    assert events[0].open == 100.0
    assert events[0].close == 100.0
    assert events[0].symbol == "BTCUSD"
    assert events[0].timeframe == "1m"
    assert events[-1].open == 102.0


def test_build_warmup_bar_events_empty_candles_produces_no_events() -> None:
    context = ExecutionContext(
        strategy_run_id="run-1", user_id="user-1", mode=ExecutionMode.PAPER
    )
    events = RuntimeFactory._build_warmup_bar_events(
        np.empty((0, 6)), "BTCUSD", "1m", context
    )
    assert events == []


async def test_runtime_factory_persists_warmup_candles_as_bar_closed_events(
    monkeypatch,
) -> None:
    """End-to-end through RuntimeFactory.build(): when ClickHouse returns
    warmup history, it must be persisted as BAR_CLOSED strategy_events, not
    just used to seed indicators."""
    candles = _candles(5)
    monkeypatch.setattr(
        "crypalgos_core.database.load_candles_from_clickhouse",
        lambda **kwargs: candles,
    )

    mock_add = MagicMock()
    mock_commit = AsyncMock()

    class MockSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            pass

        add = mock_add
        commit = mock_commit

    monkeypatch.setattr(pub_mod, "AsyncSessionLocal", MockSession)

    strategy_ns = SimpleNamespace(user_id="user-1", compiled_code=COMPILED_CODE)
    session = SimpleNamespace(
        id="sess-1",
        mode="PAPER",
        broker="delta",
        strategy=strategy_ns,
        version=None,
        environment=SessionEnvironment.PRODUCTION,
    )

    await RuntimeFactory.build(session)

    assert mock_add.call_count == 5
    persisted_types = {call.args[0].event_type for call in mock_add.call_args_list}
    assert persisted_types == {"BAR_CLOSED"}
    persisted_payloads = [call.args[0].payload for call in mock_add.call_args_list]
    assert sorted(p["candle_index"] for p in persisted_payloads) == [-5, -4, -3, -2, -1]


async def test_runtime_factory_skips_persist_when_clickhouse_unavailable(
    monkeypatch,
) -> None:
    """No warmup history (ClickHouse down, new listing, etc.) must not crash
    bootstrap -- the session still starts, just cold."""

    def _raise(**kwargs):
        raise RuntimeError("ClickHouse unavailable")

    monkeypatch.setattr(
        "crypalgos_core.database.load_candles_from_clickhouse", _raise
    )

    mock_add = MagicMock()

    class MockSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            pass

        add = mock_add
        commit = AsyncMock()

    monkeypatch.setattr(pub_mod, "AsyncSessionLocal", MockSession)

    strategy_ns = SimpleNamespace(user_id="user-1", compiled_code=COMPILED_CODE)
    session = SimpleNamespace(
        id="sess-1",
        mode="PAPER",
        broker="delta",
        strategy=strategy_ns,
        version=None,
        environment=SessionEnvironment.PRODUCTION,
    )

    runtime = await RuntimeFactory.build(session)

    assert runtime is not None
    mock_add.assert_not_called()


def test_build_warmup_indicator_snapshots_covers_every_finite_warmup_value() -> None:
    from crypalgos_core.engine.strategy_base import StrategyBase
    from crypalgos_core.indicators import Indicator

    from app.modules.strategy_service.execution.indicator_warmup import (
        IndicatorWarmup,
        discover_indicators,
    )

    class EMAWarmupStrategy(StrategyBase):
        def initialize(self) -> None:
            self.ema = Indicator.EMA(period=3).bind("btcusd", timeframe="1m")

        def on_event(self, event) -> None:
            pass

    candles = _candles(8)
    context = ExecutionContext(
        strategy_run_id="run-1", user_id="user-1", mode=ExecutionMode.PAPER
    )
    strategy = EMAWarmupStrategy(initial_capital=10_000.0, leverage=1, run_id="run-1")
    strategy.initialize()
    IndicatorWarmup(discover_indicators(strategy)).seed(candles)

    snapshots = RuntimeFactory._build_warmup_indicator_snapshots(
        strategy, candles, "BTCUSD", "1m", context
    )
    finite_indices = [
        index
        for index, value in enumerate(strategy.ema._values)
        if value is not None and np.isfinite(float(value))
    ]

    assert [snapshot.timestamp for snapshot in snapshots] == [
        int(candles[index][0]) for index in finite_indices
    ]
    assert [snapshot.candle_index for snapshot in snapshots] == [
        index - len(candles) for index in finite_indices
    ]
    assert [snapshot.bar_index for snapshot in snapshots] == [
        index - len(candles) for index in finite_indices
    ]
    assert [
        next(iter(snapshot.values.values()))["value"] for snapshot in snapshots
    ] == [float(strategy.ema._values[index]) for index in finite_indices]

    bar_sequences = {
        event.sequence_number
        for event in RuntimeFactory._build_warmup_bar_events(
            candles, "BTCUSD", "1m", context
        )
    }
    snapshot_sequences = {snapshot.sequence_number for snapshot in snapshots}
    assert bar_sequences.isdisjoint(snapshot_sequences)
    assert len(snapshot_sequences) == len(snapshots)
