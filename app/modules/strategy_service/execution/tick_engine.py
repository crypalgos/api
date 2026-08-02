import logging
from typing import Any, List, Optional

from crypalgos_core.engine.broker import ExecutionBroker
from crypalgos_core.engine.context import ExecutionContext
from crypalgos_core.engine.risk_engine import RiskEngine, RiskViolationException
from crypalgos_core.engine.strategy_base import StrategyBase
from crypalgos_core.events import Event
from crypalgos_core.events.engine_bus import EngineEventBus
from crypalgos_core.events.engine_events import (
    BarClosedEvent,
    EngineEvent,
    IndicatorSnapshotEvent,
    OrderFilledEvent,
    OrderRejectedEvent,
    PositionClosedEvent,
    PositionOpenedEvent,
    PositionReducedEvent,
    RiskViolationEvent,
)

from app.modules.strategy_service.execution.broker_compat import resolve_broker_call
from app.modules.strategy_service.execution.indicator_warmup import discover_indicators

logger = logging.getLogger(__name__)


class TickEngine:
    """Pure per-bar execution step: strategy -> risk check -> broker -> typed events.

    No persistence, no broadcast, no Redis/DB import anywhere in this file —
    trivially unit-testable against PaperBroker with zero infra running.
    Side effects (persist/broadcast/metrics) are the caller's job
    (TradingRuntime.tick(), via EventPublisher).

    Indicator VALUES are kept in sync by TradingRuntime.tick() calling
    IndicatorWarmup.on_new_bar() before this runs (see indicator_warmup.py)
    — this class only reads the now-current values back out, once per bar,
    to publish an IndicatorSnapshotEvent. IndicatorWarmup itself never
    publishes events; it only owns the numpy history / update_step() side.

    `bus` is the SAME EngineEventBus instance passed as `event_bus=` to the
    strategy's constructor (see RuntimeFactory.build() / ExecutionRunner).
    Without it, `strategy.emit(...)` — the only path compiled strategies use
    to publish ConditionEvaluatedEvent/ActionTriggeredEvent, i.e. the actual
    decision trace the Timeline tab needs — silently no-ops
    (StrategyBase.emit(): `if not self._engine_bus: return`), so a live
    session's Timeline showed bars/orders but never *why* the strategy
    acted. TickEngine subscribes to it purely to collect what the strategy
    itself published during on_event() — it never publishes its own
    Bar/Order/Position/Indicator events through the bus (callers already own
    that: ExecutionRunner re-publishes this method's return value onto its
    own bus subscribers itself; publishing here too would double-fire them).
    `next_sequence()` is also sourced from the bus when present, so
    TickEngine's own events and the strategy's self-emitted ones share one
    sequence space — required for parent_sequence/root_sequence chaining to
    resolve correctly once merged. `bus=None` (unit tests with no interest
    in decision-trace events) falls back to a private per-instance counter.
    """

    def __init__(
        self,
        strategy: StrategyBase,
        broker: ExecutionBroker,
        risk_engine: RiskEngine,
        context: ExecutionContext,
        timeframe: str,
        bus: Optional[EngineEventBus] = None,
    ) -> None:
        self.strategy = strategy
        self.broker = broker
        self.risk_engine = risk_engine
        self.context = context
        self.timeframe = timeframe
        self.bus = bus
        self._collected: List[EngineEvent] = []
        if self.bus is not None:
            self.bus.subscribe_all(self._collect)
        self._sequence = 0
        # Bumped once per process_bar() call (unlike _sequence, which bumps
        # per event) -- every event produced while processing one bar shares
        # this value, mirroring simulator.py's own per-bar index. Needed so a
        # live session's events can be grouped bar-by-bar the same way
        # backtest's buildCandleTrees groups by candle_index; before this,
        # every live event defaulted to candle_index=0.
        self._bar_index = -1

    def _collect(self, event: EngineEvent) -> None:
        self._collected.append(event)

    def _next_sequence(self) -> int:
        if self.bus is not None:
            return self.bus.next_sequence()
        self._sequence += 1
        return self._sequence

    async def process_bar(self, bar_event: Event) -> List[EngineEvent]:
        """bar_event is a fully-formed Event(type=EventType.BAR, ...) with
        data={"candle": [timestamp, open, high, low, close, volume]} — the
        same shape ExecutionRunner.on_market_tick built inline before this
        extraction. Building that Event from a raw exchange/ClickHouse tick
        is the tick source's job (TradingRuntime's caller), not this class's.
        """
        events: List[EngineEvent] = []
        self._collected = []

        candle = bar_event.data.get("candle")
        symbol = bar_event.symbol
        timestamp = bar_event.timestamp
        self._bar_index += 1

        self.strategy._current_time = timestamp
        self.strategy._current_candle = candle
        self.strategy._current_candle_index = self._bar_index
        self.strategy._current_symbol = symbol

        if (
            candle is not None
            and len(candle) > 4
            and hasattr(self.broker, "update_mark_price")
        ):
            self.broker.update_mark_price(symbol, candle[4])

        bar_seq = None
        # Recorded once per bar regardless of what the strategy does with it
        # (or whether on_event() raises below) -- the live equivalent of
        # simulator.py's own BarClosedEvent publish, and the only source of
        # OHLCV data in the live event stream for charting.
        if candle is not None and len(candle) > 5:
            bar_seq = self._next_sequence()
            # StrategyBase.emit() parents ConditionEvaluatedEvent/
            # ActionTriggeredEvent under whatever this was pointing at when
            # on_event() runs below — must be set before that call, not after.
            self.strategy._last_bar_sequence = bar_seq
            events.append(
                BarClosedEvent(
                    sequence_number=bar_seq,
                    root_sequence=bar_seq,
                    timestamp=int(timestamp),
                    candle_index=self._bar_index,
                    symbol_id=symbol,
                    symbol=symbol,
                    timeframe=self.timeframe,
                    open=float(candle[1]),
                    high=float(candle[2]),
                    low=float(candle[3]),
                    close=float(candle[4]),
                    volume=float(candle[5]),
                    context=self.context,
                )
            )

            # IndicatorWarmup.on_new_bar() (called by TradingRuntime.tick(),
            # before this method) already recomputed every discovered
            # indicator's buffer over the extended window — this just reads
            # the now-current values back out, once, into the same
            # IndicatorSnapshotEvent shape engine/timeframe.py's
            # TimeframeManager.synchronize() publishes for backtest, so the
            # frontend's indicator panel doesn't need a live-specific shape.
            snapshot = self._build_indicator_snapshot(symbol, timestamp)
            if snapshot is not None:
                events.append(snapshot)

        try:
            self.strategy.on_event(bar_event)
        except Exception:
            logger.exception(
                "Strategy on_event raised for run %s", self.context.strategy_run_id
            )
            events.extend(self._collected)
            return events

        # Whatever the strategy itself published via emit() during on_event()
        # above (ConditionEvaluatedEvent, ActionTriggeredEvent, ...) — see
        # the class docstring for why this is the only way those exist at all.
        events.extend(self._collected)

        intents = self.strategy.get_and_clear_intents()
        for intent in intents:
            pos_before = await resolve_broker_call(self.broker.get_position(intent.symbol))
            pos_qty_signed = (
                pos_before.get("qty", 0.0)
                if pos_before.get("side") == "LONG"
                else -pos_before.get("qty", 0.0)
            )

            try:
                self.risk_engine.evaluate_intent(
                    intent,
                    current_position_size=pos_qty_signed,
                    current_leverage=float(self.strategy.leverage),
                )
            except RiskViolationException as exc:
                events.append(
                    RiskViolationEvent(
                        sequence_number=self._next_sequence(),
                        timestamp=int(timestamp),
                        candle_index=self._bar_index,
                        symbol_id=intent.symbol,
                        parent_sequence=bar_seq,
                        root_sequence=bar_seq,
                        reason=str(exc),
                        context=self.context,
                    )
                )
                continue

            receipt = await resolve_broker_call(
                self.broker.submit_order(
                    symbol=intent.symbol,
                    side=intent.side,
                    qty=intent.qty,
                    price=intent.price,
                    order_type=intent.order_type,
                )
            )

            if receipt.status == "SUBMITTED":
                # A real Delta limit order may be accepted but not yet filled.
                # Record that state instead of falsely presenting it as rejected.
                from crypalgos_core.events.engine_events import OrderSubmittedEvent

                events.append(
                    OrderSubmittedEvent(
                        sequence_number=self._next_sequence(),
                        timestamp=int(receipt.timestamp * 1000),
                        candle_index=self._bar_index,
                        symbol_id=intent.symbol,
                        parent_sequence=bar_seq,
                        root_sequence=bar_seq,
                        order_id=receipt.order_id,
                        side=intent.side,
                        order_type=intent.order_type,
                        price=intent.price,
                        quantity=intent.qty,
                        context=self.context,
                    )
                )
                continue

            if receipt.status != "FILLED":
                events.append(
                    OrderRejectedEvent(
                        sequence_number=self._next_sequence(),
                        timestamp=int(receipt.timestamp * 1000),
                        candle_index=self._bar_index,
                        symbol_id=intent.symbol,
                        parent_sequence=bar_seq,
                        root_sequence=bar_seq,
                        order_id=receipt.order_id,
                        reason=receipt.status,
                        context=self.context,
                    )
                )
                continue

            events.append(
                OrderFilledEvent(
                    sequence_number=self._next_sequence(),
                    timestamp=int(receipt.timestamp * 1000),
                    candle_index=self._bar_index,
                    symbol_id=intent.symbol,
                    parent_sequence=bar_seq,
                    root_sequence=bar_seq,
                    order_id=receipt.order_id,
                    side=intent.side,
                    fill_price=receipt.average_price,
                    fill_quantity=receipt.filled_qty,
                    fee=0.0,
                    context=self.context,
                )
            )

            events.extend(
                self._position_delta_events(intent, pos_before, receipt, bar_seq)
            )

        return events

    def _build_indicator_snapshot(
        self, symbol: str, timestamp: int
    ) -> "IndicatorSnapshotEvent | None":
        """Same value-reading pattern engine/timeframe.py's synchronize() uses
        (ind._values[k], skip NaN, skip multi-output indicators with no
        single _values array) — just reading the LAST index instead of a
        TimeframeManager-tracked one, since IndicatorWarmup always recomputes
        the whole window and this runs immediately after."""
        import math

        indicators = discover_indicators(self.strategy)
        if not indicators:
            return None

        row_values: dict = {}
        for ind in indicators:
            name = getattr(ind, "name", None) or ind.__class__.__name__.lower()
            ind_values = getattr(ind, "_values", None)
            if ind_values is None or len(ind_values) == 0:
                continue
            val = ind_values[-1]
            if val is None or (isinstance(val, float) and math.isnan(val)):
                continue
            row_values[name] = {
                "node_id": getattr(ind, "node_id", None) or f"node_{name}",
                "type": ind.__class__.__name__,
                "period": getattr(ind, "period", None),
                "timeframe": getattr(ind, "timeframe", self.timeframe),
                "source": getattr(ind, "source", "close"),
                "value": float(val),
            }

        if not row_values:
            return None

        return IndicatorSnapshotEvent(
            sequence_number=self._next_sequence(),
            timestamp=int(timestamp),
            candle_index=self._bar_index,
            symbol_id=symbol,
            symbol=symbol,
            timeframe=self.timeframe,
            bar_index=self._bar_index,
            values=row_values,
            context=self.context,
        )

    def _position_delta_events(
        self, intent: Any, pos_before: dict, receipt: Any, bar_seq: "int | None"
    ) -> List[EngineEvent]:
        """Derive Position{Opened,Reduced,Closed} events by comparing broker
        position state before/after the fill, and feed realized PnL from
        closes/reductions into RiskEngine.record_realized_pnl() — previously
        nothing computed or reported realized PnL anywhere, so the risk
        engine's daily-loss-limit check was permanently dead.
        """
        events: List[EngineEvent] = []
        was_flat = pos_before.get("qty", 0.0) == 0.0
        was_side = pos_before.get("side")
        ts_ms = int(receipt.timestamp * 1000)

        if was_flat or was_side == intent.side:
            # Flat -> opening, or adding to the existing position: no close, no realized PnL.
            if was_flat:
                events.append(
                    PositionOpenedEvent(
                        sequence_number=self._next_sequence(),
                        timestamp=ts_ms,
                        candle_index=self._bar_index,
                        symbol_id=intent.symbol,
                        parent_sequence=bar_seq,
                        root_sequence=bar_seq,
                        position_id=receipt.order_id,
                        side=intent.side,
                        quantity=receipt.filled_qty,
                        entry_price=receipt.average_price,
                        context=self.context,
                    )
                )
            return events

        # Opposite side of an existing position: this fill closes or reduces it.
        entry_price = pos_before.get("entry_price", 0.0)
        prior_qty = pos_before.get("qty", 0.0)
        closed_qty = min(receipt.filled_qty, prior_qty)
        sign = 1.0 if was_side == "LONG" else -1.0
        realized_pnl = sign * (receipt.average_price - entry_price) * closed_qty

        self.risk_engine.record_realized_pnl(realized_pnl, ts_ms)

        if receipt.filled_qty >= prior_qty:
            events.append(
                PositionClosedEvent(
                    sequence_number=self._next_sequence(),
                    timestamp=ts_ms,
                    candle_index=self._bar_index,
                    symbol_id=intent.symbol,
                    parent_sequence=bar_seq,
                    root_sequence=bar_seq,
                    position_id=pos_before.get("position_id", ""),
                    order_id=receipt.order_id,
                    side=was_side,
                    fill_price=receipt.average_price,
                    realized_pnl=realized_pnl,
                    context=self.context,
                )
            )
            remaining = receipt.filled_qty - prior_qty
            if remaining > 0:
                events.append(
                    PositionOpenedEvent(
                        sequence_number=self._next_sequence(),
                        timestamp=ts_ms,
                        candle_index=self._bar_index,
                        symbol_id=intent.symbol,
                        parent_sequence=bar_seq,
                        root_sequence=bar_seq,
                        position_id=receipt.order_id,
                        side=intent.side,
                        quantity=remaining,
                        entry_price=receipt.average_price,
                        context=self.context,
                    )
                )
        else:
            events.append(
                PositionReducedEvent(
                    sequence_number=self._next_sequence(),
                    timestamp=ts_ms,
                    candle_index=self._bar_index,
                    symbol_id=intent.symbol,
                    parent_sequence=bar_seq,
                    root_sequence=bar_seq,
                    position_id=pos_before.get("position_id", ""),
                    side=was_side,
                    quantity_reduced=closed_qty,
                    remaining_quantity=prior_qty - closed_qty,
                    fill_price=receipt.average_price,
                    realized_pnl=realized_pnl,
                    context=self.context,
                )
            )

        return events
