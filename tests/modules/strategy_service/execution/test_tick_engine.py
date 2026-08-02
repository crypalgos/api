"""Unit tests for TickEngine — pure strategy -> risk -> broker execution step.

Run against PaperBroker with zero infra (no DB, no Redis, no network), as the
behavior-preservation proof for the logic previously inlined in
ExecutionRunner.on_market_tick(). Also covers the two Phase 1 bug fixes:
  - missing `await` on async broker calls (LiveExchangeBroker-shaped brokers)
  - RiskEngine's daily-loss-limit check, previously dead because nothing
    ever called update_daily_loss()/record_realized_pnl()
"""

from typing import Any, Dict, Optional

import numpy as np
import pytest

from crypalgos_core.engine.broker import ExecutionBroker, OrderReceipt
from crypalgos_core.engine.context import ExecutionContext, ExecutionMode
from crypalgos_core.engine.risk_engine import RiskEngine
from crypalgos_core.engine.strategy_base import StrategyBase
from crypalgos_core.events import Event, EventType
from crypalgos_core.events.engine_events import (
    BarClosedEvent,
    IndicatorSnapshotEvent,
    OrderFilledEvent,
    PositionClosedEvent,
    PositionOpenedEvent,
    RiskViolationEvent,
)
from crypalgos_core.indicators import Indicator

from app.modules.strategy_service.execution.tick_engine import TickEngine
from app.modules.strategy_service.paper_broker import PaperBroker


class ScriptedStrategy(StrategyBase):
    """A strategy whose action per bar is controlled by the test via `.action`.
    `action` is a zero-arg callable invoked from on_event(); it calls
    self.buy()/self.sell() (or does nothing) exactly like a compiled strategy
    would in response to a condition firing.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.action = None

    def initialize(self) -> None:
        pass

    def on_event(self, event: Event) -> None:
        if self.action is not None:
            self.action()


def make_bar(symbol: str, close: float, timestamp: int) -> Event:
    return Event(
        type=EventType.BAR,
        timestamp=timestamp,
        symbol=symbol,
        data={"candle": [timestamp, close, close, close, close, 1.0]},
    )


def make_context() -> ExecutionContext:
    return ExecutionContext(
        strategy_run_id="test-run", user_id="test-user", mode=ExecutionMode.PAPER
    )


def make_engine(strategy: ScriptedStrategy, broker: Any) -> TickEngine:
    return TickEngine(
        strategy=strategy,
        broker=broker,
        risk_engine=RiskEngine(max_leverage=20.0, daily_loss_limit=100.0),
        context=make_context(),
        timeframe="1m",
    )


async def test_opening_a_position_emits_filled_and_opened_events() -> None:
    strategy = ScriptedStrategy(initial_capital=10_000.0, leverage=1, run_id="test-run")
    broker = PaperBroker(initial_capital=10_000.0)
    engine = make_engine(strategy, broker)

    strategy.action = lambda: strategy.buy("BTCUSD", amount=1.0)
    events = await engine.process_bar(make_bar("BTCUSD", 100.0, 1_000))

    event_types = [type(e) for e in events]
    assert OrderFilledEvent in event_types
    assert PositionOpenedEvent in event_types
    opened = next(e for e in events if isinstance(e, PositionOpenedEvent))
    assert opened.side == "LONG"
    assert opened.quantity == 1.0
    assert opened.entry_price == 100.0


async def test_risk_violation_blocks_order_without_killing_the_tick() -> None:
    strategy = ScriptedStrategy(initial_capital=10_000.0, leverage=1, run_id="test-run")
    broker = PaperBroker(initial_capital=10_000.0)
    engine = make_engine(strategy, broker)
    engine.risk_engine.kill_switch_active = True

    strategy.action = lambda: strategy.buy("BTCUSD", amount=1.0)
    events = await engine.process_bar(make_bar("BTCUSD", 100.0, 1_000))

    # Every bar always emits BarClosedEvent first, regardless of what the
    # strategy does with it -- the actual point of this test is that exactly
    # one RiskViolationEvent follows and nothing else (no OrderFilled).
    non_bar_events = [e for e in events if not isinstance(e, BarClosedEvent)]
    assert len(non_bar_events) == 1
    assert isinstance(non_bar_events[0], RiskViolationEvent)
    assert "Kill switch" in non_bar_events[0].reason


async def test_losing_close_increments_daily_loss_and_then_trips_limit() -> None:
    """Regression test for the dead RiskEngine._current_daily_loss bug: before
    this fix, nothing ever called update_daily_loss(), so a strategy could
    lose past its daily_loss_limit with the check never firing.
    """
    strategy = ScriptedStrategy(initial_capital=10_000.0, leverage=1, run_id="test-run")
    broker = PaperBroker(initial_capital=10_000.0)
    engine = make_engine(strategy, broker)
    engine.risk_engine.daily_loss_limit = 50.0

    # Bar 1: open a 1-unit long at 100.
    strategy.action = lambda: strategy.buy("BTCUSD", amount=1.0)
    await engine.process_bar(make_bar("BTCUSD", 100.0, 1_000))

    # Bar 2: close it at 40 -> realized loss of 60, past the 50 limit.
    strategy.action = lambda: strategy.sell("BTCUSD", amount=1.0)
    events = await engine.process_bar(make_bar("BTCUSD", 40.0, 2_000))

    closed = next(e for e in events if isinstance(e, PositionClosedEvent))
    assert closed.realized_pnl == -60.0
    assert engine.risk_engine._current_daily_loss == 60.0

    # Bar 3: any further entry must now be blocked by the (now-live) daily-loss check.
    strategy.action = lambda: strategy.buy("BTCUSD", amount=1.0)
    events = await engine.process_bar(make_bar("BTCUSD", 41.0, 3_000))
    non_bar_events = [e for e in events if not isinstance(e, BarClosedEvent)]
    assert len(non_bar_events) == 1
    assert isinstance(non_bar_events[0], RiskViolationEvent)
    assert "Daily loss limit" in non_bar_events[0].reason


class _FakeAsyncBroker(ExecutionBroker):
    """Mirrors LiveExchangeBroker's shape: submit_order/get_position/get_balances
    are `async def`, unlike PaperBroker's synchronous methods. Used to prove
    TickEngine actually awaits these instead of receiving a bare coroutine
    object (the exact bug being fixed at runner.py:186,201).
    """

    def __init__(self) -> None:
        self.submit_order_calls = 0

    async def submit_order(
        self, symbol: str, side: str, qty: float, price: float, order_type: str
    ) -> OrderReceipt:
        self.submit_order_calls += 1
        return OrderReceipt(
            order_id="fake-1",
            status="FILLED",
            filled_qty=qty,
            average_price=100.0,
            timestamp=1.0,
        )

    async def cancel_order(self, order_id: str) -> bool:
        return True

    async def get_position(self, symbol: str) -> Dict[str, Any]:
        return {
            "position_id": "",
            "symbol": symbol,
            "side": "LONG",
            "qty": 0.0,
            "entry_price": 0.0,
            "unrealized_pnl": 0.0,
        }

    async def get_balances(self) -> Dict[str, Any]:
        return {"cash": 10_000.0, "equity": 10_000.0}


async def test_async_broker_is_actually_awaited() -> None:
    strategy = ScriptedStrategy(initial_capital=10_000.0, leverage=1, run_id="test-run")
    broker = _FakeAsyncBroker()
    engine = make_engine(strategy, broker)

    strategy.action = lambda: strategy.buy("BTCUSD", amount=1.0)
    events = await engine.process_bar(make_bar("BTCUSD", 100.0, 1_000))

    # If submit_order()/get_position() weren't awaited, TickEngine would be
    # working with coroutine objects instead of dicts/OrderReceipt, and this
    # would raise (AttributeError: 'coroutine' object has no attribute 'get'/
    # 'status') well before reaching this assertion.
    assert broker.submit_order_calls == 1
    filled = next(e for e in events if isinstance(e, OrderFilledEvent))
    assert filled.fill_price == 100.0


async def test_bar_closed_emitted_once_per_bar_with_correct_ohlcv() -> None:
    """Regression test: BarClosedEvent was only ever constructed in the
    backtest simulator -- live sessions had no candle data in their event
    stream at all, so there was nothing to chart. Every process_bar() call
    must now emit exactly one, with the raw candle's OHLCV."""
    strategy = ScriptedStrategy(initial_capital=10_000.0, leverage=1, run_id="test-run")
    broker = PaperBroker(initial_capital=10_000.0)
    engine = make_engine(strategy, broker)

    events = await engine.process_bar(
        Event(
            type=EventType.BAR,
            timestamp=1_000,
            symbol="BTCUSD",
            data={"candle": [1_000, 100.0, 105.0, 98.0, 102.0, 50.0]},
        )
    )

    bar_events = [e for e in events if isinstance(e, BarClosedEvent)]
    assert len(bar_events) == 1
    bar = bar_events[0]
    assert bar.symbol == "BTCUSD"
    assert bar.timeframe == "1m"
    assert (bar.open, bar.high, bar.low, bar.close, bar.volume) == (
        100.0,
        105.0,
        98.0,
        102.0,
        50.0,
    )


async def test_bar_closed_emitted_even_when_strategy_raises() -> None:
    """BarClosedEvent must be recorded regardless of what the strategy does
    with the bar -- the candle itself closed either way."""

    class RaisingStrategy(StrategyBase):
        def initialize(self) -> None:
            pass

        def on_event(self, event: Event) -> None:
            raise RuntimeError("boom")

    strategy = RaisingStrategy(initial_capital=10_000.0, leverage=1, run_id="test-run")
    broker = PaperBroker(initial_capital=10_000.0)
    engine = make_engine(strategy, broker)

    events = await engine.process_bar(make_bar("BTCUSD", 100.0, 1_000))

    assert len(events) == 1
    assert isinstance(events[0], BarClosedEvent)


async def test_all_events_from_one_bar_share_candle_index() -> None:
    """Every event TickEngine produces while processing one bar -- the
    BarClosedEvent and whatever the strategy's action triggered -- must
    share the same candle_index, or a live session's events could never be
    grouped bar-by-bar the way buildCandleTrees groups backtest events."""
    strategy = ScriptedStrategy(initial_capital=10_000.0, leverage=1, run_id="test-run")
    broker = PaperBroker(initial_capital=10_000.0)
    engine = make_engine(strategy, broker)

    strategy.action = lambda: strategy.buy("BTCUSD", amount=1.0)
    events = await engine.process_bar(make_bar("BTCUSD", 100.0, 1_000))

    assert len(events) >= 2  # BarClosedEvent + OrderFilledEvent + PositionOpenedEvent
    candle_indices = {e.candle_index for e in events}
    assert candle_indices == {0}


async def test_candle_index_increments_bar_over_bar() -> None:
    strategy = ScriptedStrategy(initial_capital=10_000.0, leverage=1, run_id="test-run")
    broker = PaperBroker(initial_capital=10_000.0)
    engine = make_engine(strategy, broker)

    events_1 = await engine.process_bar(make_bar("BTCUSD", 100.0, 1_000))
    events_2 = await engine.process_bar(make_bar("BTCUSD", 101.0, 2_000))
    events_3 = await engine.process_bar(make_bar("BTCUSD", 102.0, 3_000))

    assert {e.candle_index for e in events_1} == {0}
    assert {e.candle_index for e in events_2} == {1}
    assert {e.candle_index for e in events_3} == {2}


async def test_indicator_snapshot_emitted_from_current_indicator_values() -> None:
    """Regression test: TickEngine never read indicator values back out at
    all before this fix, so a live session's IndicatorSnapshotEvent stream
    was permanently empty regardless of what IndicatorWarmup.on_new_bar()
    updated -- the frontend's indicator panel had nothing to render. This
    mirrors what TradingRuntime.tick() actually does: seed + advance the
    indicator via IndicatorWarmup, then hand the bar to TickEngine, which
    must read the now-current value back out.
    """
    strategy = ScriptedStrategy(initial_capital=10_000.0, leverage=1, run_id="test-run")
    ema = Indicator.EMA(period=2)
    ema.name = "ema_fast"
    ema.datasource = "btcusd"
    ema.timeframe = "1m"
    strategy.ema_fast = ema
    broker = PaperBroker(initial_capital=10_000.0)
    engine = make_engine(strategy, broker)

    # Mirrors IndicatorWarmup.on_new_bar(): recompute over the full window,
    # then advance the cursor to the newest index.
    closes = np.asarray([100.0, 101.0, 102.0], dtype=np.float64)
    ema.compute(closes)
    ema.update_step(len(closes) - 1)

    events = await engine.process_bar(make_bar("BTCUSD", 102.0, 3_000))

    snapshots = [e for e in events if isinstance(e, IndicatorSnapshotEvent)]
    assert len(snapshots) == 1
    assert "ema_fast" in snapshots[0].values
    assert snapshots[0].values["ema_fast"]["value"] == pytest.approx(
        float(ema._values[-1])
    )
