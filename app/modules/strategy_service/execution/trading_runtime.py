import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Type

from crypalgos_core.engine.context import ExecutionContext, ExecutionMode
from crypalgos_core.engine.risk_engine import RiskEngine
from crypalgos_core.engine.strategy_base import StrategyBase
from crypalgos_core.engine.timeframe import timeframe_to_milliseconds
from crypalgos_core.events import Event
from crypalgos_core.events.engine_bus import EngineEventBus
from crypalgos_core.events.engine_events import (
    BarClosedEvent,
    EngineEvent,
    IndicatorSnapshotEvent,
)

from app.modules.strategy_service.execution.candle_aggregator import (
    RAW_TICK_TIMEFRAME_MS,
    CandleAggregator,
    FormingCandle,
)
from app.modules.strategy_service.execution.event_publisher import EventPublisher
from app.modules.strategy_service.execution.indicator_warmup import (
    IndicatorWarmup,
    discover_indicators,
)
from app.modules.strategy_service.execution.session_metrics import SessionMetrics
from app.modules.strategy_service.execution.tick_engine import TickEngine
from app.modules.strategy_service.models.live_trading_session_model import (
    SessionEnvironment,
)
from app.modules.strategy_service.services.session_workspace_archive import (
    SessionArchiveError,
    SessionWorkspaceArchive,
)
from app.modules.strategy_service.utils.broker_factory import BrokerFactory

logger = logging.getLogger(__name__)

# How many historical bars to seed indicators with at bootstrap (see
# indicator_warmup.py). The live viewer shows these fixed historical bars plus
# one mutable PRICE_TICK candle, matching an exchange terminal on first load.
WARMUP_BAR_COUNT = 1000

# Bound on how long a just-closed bar's execution waits for Delta's own
# finalized candle before falling back to the locally-aggregated one (see
# TradingRuntime._reconcile_official_candle()). Deliberately generous
# relative to a raw 1-minute tick: even a 1m strategy only pays this once
# per closed bar, and the alternative -- letting the archived/replayed
# candle silently diverge from what a trader sees on Delta -- is the exact
# trust problem this reconciliation exists to close.
RECONCILE_TIMEOUT_SECS = 2.0


class TradingRuntime:
    """Per-session composition root: owns strategy/broker/risk_engine/context,
    a TickEngine, SessionMetrics, and an EventPublisher.

    LiveTradingRunner (Celery, Phase 2) and the transitional ExecutionRunner
    (Path B, until retired) both drive a TradingRuntime built the same way —
    provably running identical execution, not just similar logic.
    """

    def __init__(
        self,
        strategy: StrategyBase,
        broker: Any,
        risk_engine: RiskEngine,
        context: ExecutionContext,
        timeframe: str,
        symbol: Optional[str] = None,
        indicator_warmup: Optional[IndicatorWarmup] = None,
        candle_aggregator: Optional[CandleAggregator] = None,
        bus: Optional[EngineEventBus] = None,
        session_archive: Optional[SessionWorkspaceArchive] = None,
        environment: Optional[SessionEnvironment] = None,
        market_data_adapter: Optional[Any] = None,
    ) -> None:
        self.strategy = strategy
        self.broker = broker
        self.risk_engine = risk_engine
        self.context = context
        self.session_id = context.strategy_run_id
        self.timeframe = timeframe
        # Only populated by RuntimeFactory.build() (Path A) — tells
        # LiveTradingRunner which tick source to subscribe. ExecutionRunner
        # (Path B) constructs TradingRuntime directly and already gets its
        # ticks from a callback registered on live_feed_subscriber, so it
        # has no use for this.
        self.symbol = symbol
        # Found during Phase 3 end-to-end verification: without this, every
        # live bar's on_event() crashed with IndexError (indicator buffers
        # start completely empty -- backtest's precompute-over-full-history
        # step has no live equivalent otherwise). None only for callers that
        # don't want indicator seeding (e.g. a unit test driving TickEngine
        # directly against a strategy with no indicators).
        self.indicator_warmup = indicator_warmup
        # Also found during Phase 3 verification: Delta's WS feed only ever
        # publishes 1-minute candle closes, but a strategy can declare any
        # timeframe (e.g. "1h") -- without this, on_event() fired once per
        # real minute using indicators seeded (correctly) from hourly
        # history but fed minute-by-minute live appends, silently
        # corrupting them. None when the strategy's own timeframe already
        # matches the raw tick granularity (see RuntimeFactory.build()).
        self.candle_aggregator = candle_aggregator
        # This mutable projection receives every Delta ticker/candle revision
        # for the live chart only. It is never read by TickEngine or archive
        # code; execution stays gated by finalized bars below.
        self.forming_candle = FormingCandle(timeframe)
        # Same EngineEventBus passed as `event_bus=` to the strategy's own
        # constructor (see RuntimeFactory.build() / ExecutionRunner) — must
        # be, so TickEngine's collected decision-trace events and its own
        # order/position events share one sequence space. See TickEngine's
        # docstring for the full reasoning.
        self.bus = bus
        self.tick_engine = TickEngine(strategy, broker, risk_engine, context, timeframe, bus)
        self.metrics = SessionMetrics()
        self.session_archive = session_archive
        self.event_publisher = EventPublisher(
            self.session_id, self.metrics, archive=session_archive
        )
        # Only set (by RuntimeFactory.build()) for TESTNET sessions -- see
        # _reconcile_official_candle()'s docstring for why PRODUCTION is
        # deliberately out of scope here.
        self.environment = environment
        self.market_data_adapter = market_data_adapter

    async def _broadcast_forming_candle(
        self, symbol: str, candle: List[float], source_timestamp: int
    ) -> None:
        """Broadcast the mutable UI-only candle without persisting it."""
        await self.event_publisher.broadcast_raw(
            {
                "type": "PRICE_TICK",
                "sequence_number": 0,
                # The bucket start identifies the mutable chart candle. The
                # original exchange time remains available for freshness
                # checks; it must not be replaced by the bucket timestamp.
                "timestamp": int(candle[0]),
                "source_timestamp": int(source_timestamp),
                "payload": {
                    "symbol": symbol,
                    "open": candle[1],
                    "high": candle[2],
                    "low": candle[3],
                    "close": candle[4],
                    "volume": candle[5],
                },
            }
        )

    async def _reconcile_official_candle(
        self, local_candle: List[float]
    ) -> List[float]:
        """Swaps a just-closed, locally-aggregated bucket for Delta's own
        official candle covering the exact same window, before it feeds
        indicators, execution, the archive, or any broadcast/persisted
        event -- so every downstream consumer (live decisions, replay,
        analytics) agrees on one value instead of the trader's own strategy
        seeing a locally-rolled-up close while the archived/replayed record
        shows a different, "official" one for the same bar.

        Deliberately bounded by RECONCILE_TIMEOUT_SECS rather than awaited
        indefinitely: execution must still fire close to the instant the
        broker considers the bar closed, not stall on a REST round-trip.
        Falls back to the local aggregate -- unchanged -- on timeout,
        network failure, or Delta simply not having published that bucket's
        candle yet; this is a best-effort correction; it must never be
        allowed to kill a live session over its own unavailability.

        TESTNET-only for now: TESTNET's tick source already reads Delta's
        own WS feed directly (tick_sources.py), so a REST call back to the
        same exchange for the just-closed bucket is a natural fit. Mainnet
        sessions already source finalized bars from ClickHouse (see
        _fetch_warmup_candles) -- reconciling *live* mainnet bars against
        ClickHouse would depend on that pipeline's own ingestion latency,
        a materially different (and unrequested) problem from this one.
        """
        if self.environment != SessionEnvironment.TESTNET or self.market_data_adapter is None:
            return local_candle

        bucket_start = int(local_candle[0])
        try:
            official = await asyncio.wait_for(
                self.market_data_adapter.fetch_ohlcv(
                    symbol=self.symbol,
                    timeframe=self.timeframe,
                    since_ms=bucket_start,
                    limit=2,
                ),
                timeout=RECONCILE_TIMEOUT_SECS,
            )
        except Exception:
            logger.warning(
                "Reconciliation fetch failed for session %s bucket %d — "
                "using locally-aggregated candle.",
                self.session_id,
                bucket_start,
                exc_info=True,
            )
            return local_candle

        for candle in official:
            if candle.timestamp_ms == bucket_start:
                return [
                    float(candle.timestamp_ms),
                    float(candle.open),
                    float(candle.high),
                    float(candle.low),
                    float(candle.close),
                    float(candle.volume),
                ]

        logger.warning(
            "Delta had not published an official candle for session %s "
            "bucket %d within %.1fs — using locally-aggregated candle.",
            self.session_id,
            bucket_start,
            RECONCILE_TIMEOUT_SECS,
        )
        return local_candle

    async def tick(self, bar_event: Event) -> List[EngineEvent]:
        """Process one raw tick end-to-end: aggregate to the strategy's
        declared timeframe -> warm up indicators -> TickEngine -> persist ->
        broadcast -> metrics.

        Returns [] without running the strategy at all when the aggregator
        is still accumulating a partial bucket -- that is expected and
        correct on most calls when the strategy's timeframe is coarser than
        the raw 1-minute tick granularity, not a failure.

        Callers that need TickEngine's output without these side effects
        (e.g. ExecutionRunner during the Path A/B migration window, which
        already has its own persistence/broadcast wiring) should call
        `self.tick_engine.process_bar(bar_event)` directly instead — but
        must then handle aggregation and indicator warmup themselves too.
        """
        ticker = bar_event.data.get("ticker")
        if ticker is not None:
            price = float(ticker.get("price", 0))
            if price > 0:
                display_candle = self.forming_candle.update_price(
                    bar_event.timestamp, price
                )
                if display_candle is not None:
                    await self._broadcast_forming_candle(
                        bar_event.symbol, display_candle, bar_event.timestamp
                    )
            return []

        raw_candle = bar_event.data.get("candle")
        if raw_candle is None:
            return []

        # This projection consumes both ticker prices and revisable raw
        # candles. It is intentionally outside the finalized execution path:
        # every update redraws the last live candle but cannot alter an
        # indicator, create an order, persist, or enter deterministic replay.
        display_candle = self.forming_candle.update_candle(raw_candle)
        if not bar_event.data.get("is_closed", True):
            if display_candle is not None:
                await self._broadcast_forming_candle(
                    bar_event.symbol, display_candle, bar_event.timestamp
                )
            return []

        if display_candle is not None:
            await self._broadcast_forming_candle(
                bar_event.symbol, display_candle, bar_event.timestamp
            )

        if self.candle_aggregator is not None:
            closed_candle = self.candle_aggregator.add_tick(raw_candle)
            if closed_candle is None:
                # The live display projection above has already redrawn this
                # partial bucket. Execution still waits for the aggregator to
                # prove the timeframe candle closed.
                return []
            # Bounded, best-effort swap for Delta's own official candle over
            # this exact bucket (see _reconcile_official_candle()'s
            # docstring) -- everything below (indicators, execution, the
            # archive, persisted/broadcast BAR_CLOSED) reads the reconciled
            # value uniformly, so replay can never diverge from what the
            # strategy actually saw.
            closed_candle = await self._reconcile_official_candle(closed_candle)
            bar_event = Event(
                type=bar_event.type,
                timestamp=int(closed_candle[0]),
                symbol=bar_event.symbol,
                data={"candle": closed_candle},
            )

        if self.session_archive is not None:
            try:
                self.session_archive.append_candle(bar_event.data["candle"])
            except Exception as exc:
                logger.exception(
                    "Failed to archive finalized Testnet candle for session %s",
                    self.session_id,
                )
                raise SessionArchiveError(
                    f"Cannot preserve deterministic replay for session {self.session_id}"
                ) from exc

        if self.indicator_warmup is not None:
            candle = bar_event.data.get("candle")
            if candle is not None:
                self.indicator_warmup.on_new_bar(candle)
        events = await self.tick_engine.process_bar(bar_event)
        self.metrics.record_bar()
        if events:
            await self.event_publisher.persist(events)
            await self.event_publisher.broadcast(events)
            self.event_publisher.record_metrics(events)
        return events

    async def flush(self) -> dict[str, str] | None:
        """Force-flush events and finalize the deterministic Testnet archive
        (upload -> verify -> delete local). Returns the artifact manifest to
        persist on the session row, or None if there's no archive for this
        session (non-Testnet) or archiving failed and should be retried later."""
        await self.event_publisher.flush()
        if self.session_archive is not None:
            return await self.session_archive.close()
        return None


class RuntimeFactory:
    """The single place a LiveTradingSession DB row becomes a fully-wired
    TradingRuntime, replacing the ad hoc BrokerFactory-in-_bootstrap()
    construction that LiveTradingRunner used before this extraction.
    """

    @staticmethod
    def _load_strategy_class(code_str: str) -> Type[StrategyBase]:
        """Same dynamic-exec approach as StrategyManager._load_strategy_class_from_code
        — duplicated rather than imported to avoid a strategy_service.services ->
        execution -> services import cycle; both are two-line reflection helpers,
        not logic worth sharing via inheritance."""
        namespace: Dict[str, Any] = {}
        exec(code_str, namespace)
        for val in namespace.values():
            if (
                isinstance(val, type)
                and issubclass(val, StrategyBase)
                and val is not StrategyBase
            ):
                return val
        raise ValueError("No valid Strategy subclass found in compiled code.")

    @staticmethod
    def _resolve_primary_symbol(strat_class: Type[StrategyBase]) -> str:
        """Compiled strategy classes carry a class-level `datasources` dict
        keyed by datasource id, each with a "symbol" field (set by the DAG
        compiler from the canvas's datasource node — see
        crypalgos_core/compiler/semantic_analyzer.py). Live trading (this
        phase) is single-symbol only, matching the plan's non-goals — the
        first datasource's symbol is "the" symbol for the session.
        """
        datasources = getattr(strat_class, "datasources", None) or {}
        for ds in datasources.values():
            symbol = ds.get("symbol")
            if symbol:
                return symbol
        raise ValueError(
            "Compiled strategy has no datasource with a symbol — cannot "
            "determine what to subscribe to for live trading."
        )

    @staticmethod
    def _resolve_primary_timeframe(strat_class: Type[StrategyBase]) -> str:
        """Same datasources dict _resolve_primary_symbol reads, for the
        timeframe string instead. Single-symbol/single-timeframe live
        trading (this phase) means the first datasource's first timeframe
        is "the" timeframe to seed and subscribe on."""
        datasources = getattr(strat_class, "datasources", None) or {}
        for ds in datasources.values():
            timeframes = ds.get("timeframes") or []
            if timeframes:
                return timeframes[0]
        raise ValueError(
            "Compiled strategy has no datasource with a timeframe — cannot "
            "determine what candle interval to seed/subscribe for live trading."
        )

    @staticmethod
    async def _fetch_warmup_candles(
        environment: SessionEnvironment, exchange: str, symbol: str, timeframe: str
    ) -> Optional[Any]:
        """Load finalized warmup bars from the session's immutable market."""
        tf_ms = timeframe_to_milliseconds(timeframe)
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(milliseconds=tf_ms * (WARMUP_BAR_COUNT + 5))
        try:
            if environment == SessionEnvironment.PRODUCTION:
                from crypalgos_core.database import load_candles_from_clickhouse

                return load_candles_from_clickhouse(
                    exchange=exchange,
                    symbol=symbol,
                    start_date=start_date,
                    end_date=end_date,
                    timeframe=timeframe,
                )

            from crypalgos_data.exchanges.delta_market_data import (
                DeltaMarketDataAdapter,
            )

            adapter = DeltaMarketDataAdapter(testnet=True)
            candles = await adapter.fetch_ohlcv(
                symbol=symbol,
                timeframe=timeframe,
                since_ms=int(start_date.timestamp() * 1000),
                limit=WARMUP_BAR_COUNT + 5,
            )
            now_ms = int(end_date.timestamp() * 1000)
            finalized = [
                [c.timestamp_ms, c.open, c.high, c.low, c.close, c.volume]
                for c in candles
                if c.timestamp_ms + tf_ms <= now_ms
            ]
            return finalized[-WARMUP_BAR_COUNT:]
        except Exception:
            logger.exception(
                "Failed to fetch %s warmup history for %s/%s %s — indicators "
                "and chart will start cold.",
                environment,
                exchange,
                symbol,
                timeframe,
            )
            return None

    @staticmethod
    def _seed_indicators(strategy: StrategyBase, candles: Optional[Any]) -> IndicatorWarmup:
        """Seeds every indicator the strategy declared from the fetched
        warmup candles, so the first live bar already has whatever lookback
        the strategy's compiled conditions need. See indicator_warmup.py for
        why this exists and how it stays in sync on every subsequent live
        bar via TradingRuntime.tick().
        """
        indicators = discover_indicators(strategy)
        warmup = IndicatorWarmup(indicators)
        if indicators and candles is not None and len(candles) > 0:
            warmup.seed(candles)
        return warmup

    @staticmethod
    def _build_warmup_bar_events(
        candles: Any, symbol: str, timeframe: str, context: ExecutionContext
    ) -> List[BarClosedEvent]:
        """Historical candles never flow through TickEngine.process_bar()
        (only live ticks do), so without this the event stream — and
        therefore any chart built from it — has zero OHLCV data until the
        first genuinely new live bar closes. Numbered with negative
        sequence_number/candle_index so they sort strictly before
        TickEngine's own (0-based, positive) numbering for this same
        session: no collision, correct chronological order once merged.
        """
        n = len(candles)
        events: List[BarClosedEvent] = []
        for i, row in enumerate(candles):
            offset = n - i  # counts down: -n, -n+1, ..., -1
            events.append(
                BarClosedEvent(
                    sequence_number=-offset,
                    timestamp=int(row[0]),
                    candle_index=-offset,
                    symbol_id=symbol,
                    symbol=symbol,
                    timeframe=timeframe,
                    open=float(row[1]),
                    high=float(row[2]),
                    low=float(row[3]),
                    close=float(row[4]),
                    volume=float(row[5]),
                    context=context,
                )
            )
        return events

    @staticmethod
    def _build_warmup_indicator_snapshots(
        strategy: StrategyBase,
        candles: Any,
        symbol: str,
        timeframe: str,
        context: ExecutionContext,
    ) -> List[IndicatorSnapshotEvent]:
        """Materialize seeded indicator history for every warmup candle.

        IndicatorWarmup.seed() fills each indicator's internal value buffer,
        but the chart only knows persisted ``INDICATOR_SNAPSHOT`` events. A
        single terminal snapshot made every overlay render as a short segment
        on the last warmup candle. Keep early lookback values absent when they
        are non-finite, exactly as finalized live/backtest snapshots do.

        Warmup bars retain their established sequence range ``[-n, -1]``.
        Snapshots use ``[-2n, -n-1]`` so event identities are unique while
        ``bar_index``/``candle_index`` remain the actual candle join keys.
        """
        import math

        indicators = discover_indicators(strategy)
        if not indicators:
            return []

        count = len(candles)
        snapshots: List[IndicatorSnapshotEvent] = []
        for index, row in enumerate(candles):
            values: dict[str, dict[str, Any]] = {}
            for indicator in indicators:
                indicator_values = getattr(indicator, "_values", None)
                if indicator_values is None or index >= len(indicator_values):
                    continue
                try:
                    value = float(indicator_values[index])
                except (TypeError, ValueError):
                    continue
                if not math.isfinite(value):
                    continue

                name = (
                    getattr(indicator, "name", None)
                    or indicator.__class__.__name__.lower()
                )
                values[name] = {
                    "node_id": getattr(indicator, "node_id", None)
                    or f"node_{name}",
                    "type": indicator.__class__.__name__,
                    "period": getattr(indicator, "period", None),
                    "timeframe": getattr(indicator, "timeframe", timeframe),
                    "source": getattr(indicator, "source", "close"),
                    "value": value,
                }

            if not values:
                continue
            candle_index = index - count
            snapshots.append(
                IndicatorSnapshotEvent(
                    sequence_number=-2 * count + index,
                    timestamp=int(row[0]),
                    candle_index=candle_index,
                    symbol_id=symbol,
                    symbol=symbol,
                    timeframe=timeframe,
                    bar_index=candle_index,
                    values=values,
                    context=context,
                )
            )
        return snapshots

    @staticmethod
    async def build(
        session: Any,
        credentials: Optional[Dict[str, str]] = None,
        initial_capital: float = 10000.0,
        leverage: int = 1,
    ) -> "TradingRuntime":
        """session is a LiveTradingSession row (with .strategy and .version
        relationships loaded). Prefers the pinned version's compiled_code when
        version_id is set — a live session should run the strategy code it was
        deployed with, not whatever the strategy's latest saved code is —
        falling back to the strategy's current code when no version is pinned.
        """
        compiled_code = (
            session.version.compiled_code
            if session.version is not None
            else session.strategy.compiled_code
        )
        strat_class = RuntimeFactory._load_strategy_class(compiled_code)
        symbol = RuntimeFactory._resolve_primary_symbol(strat_class)
        timeframe = RuntimeFactory._resolve_primary_timeframe(strat_class)
        exchange = getattr(strat_class, "exchange", session.broker)

        api_key = (credentials or {}).get("api_key", "")
        api_secret = (credentials or {}).get("api_secret", "")
        environment = session.environment
        testnet = environment == SessionEnvironment.TESTNET

        broker = BrokerFactory.create(
            mode=session.mode,
            broker=session.broker,
            api_key=api_key,
            api_secret=api_secret,
            testnet=testnet,
        )

        risk_engine = RiskEngine(max_leverage=float(leverage))

        context = ExecutionContext(
            strategy_run_id=session.id,
            user_id=session.strategy.user_id,
            mode=ExecutionMode(session.mode),
        )

        # Without a real bus here, strategy.emit() — the only path compiled
        # strategies use to publish ConditionEvaluatedEvent/
        # ActionTriggeredEvent — silently no-ops (StrategyBase.emit():
        # `if not self._engine_bus: return`), so a live session's decision
        # trace (what the Timeline tab needs) was always empty regardless of
        # what actually happened. See TickEngine's docstring for the full
        # reasoning on why this same bus also becomes TickEngine's sequence
        # source, not just the strategy's.
        bus = EngineEventBus()
        strategy = strat_class(
            initial_capital=initial_capital,
            leverage=leverage,
            run_id=session.id,
            event_bus=bus,
        )
        strategy.is_live = True
        strategy.initialize()

        warmup_candles = await RuntimeFactory._fetch_warmup_candles(
            environment, exchange, symbol, timeframe
        )
        indicator_warmup = RuntimeFactory._seed_indicators(strategy, warmup_candles)
        session_archive = (
            SessionWorkspaceArchive(
                session.strategy_id,
                session.id,
                {
                    "execution_mode": session.mode,
                    "exchange": session.exchange,
                    "environment": environment.value,
                    "symbol": symbol,
                    "timeframe": timeframe,
                },
            )
            if environment == SessionEnvironment.TESTNET
            else None
        )
        if session_archive is not None and warmup_candles is not None:
            session_archive.append_candles(warmup_candles)

        # Shared across every closed bar this session ever reconciles (see
        # TradingRuntime._reconcile_official_candle()) rather than
        # constructed per-bar -- reuses the adapter's symbol-normalizer
        # cache instead of rebuilding it on every bar close. Only
        # constructed for TESTNET, matching _fetch_warmup_candles' own
        # environment branching.
        market_data_adapter = None
        if environment == SessionEnvironment.TESTNET:
            from crypalgos_data.exchanges.delta_market_data import (
                DeltaMarketDataAdapter,
            )

            market_data_adapter = DeltaMarketDataAdapter(testnet=True)

        # Delta's WS feed only ever delivers 1-minute candle closes; only
        # construct an aggregator when the strategy's own timeframe is
        # actually coarser than that (a "1m" strategy needs no aggregation
        # at all, and forcing one through would add a spurious one-tick
        # delay that doesn't exist in the un-aggregated path today).
        candle_aggregator = (
            CandleAggregator(timeframe)
            if timeframe_to_milliseconds(timeframe) != RAW_TICK_TIMEFRAME_MS
            else None
        )

        logger.info(
            "RuntimeFactory built TradingRuntime for session %s (mode=%s environment=%s exchange=%s symbol=%s timeframe=%s aggregation=%s)",
            session.id,
            session.mode,
            environment,
            exchange,
            symbol,
            timeframe,
            candle_aggregator is not None,
        )
        runtime = TradingRuntime(
            strategy=strategy,
            broker=broker,
            risk_engine=risk_engine,
            context=context,
            timeframe=timeframe,
            symbol=symbol,
            indicator_warmup=indicator_warmup,
            candle_aggregator=candle_aggregator,
            bus=bus,
            session_archive=session_archive,
            environment=environment,
            market_data_adapter=market_data_adapter,
        )

        if warmup_candles is not None and len(warmup_candles) > 0:
            warmup_events: List[EngineEvent] = RuntimeFactory._build_warmup_bar_events(
                warmup_candles, symbol, timeframe, context
            )
            warmup_events.extend(
                RuntimeFactory._build_warmup_indicator_snapshots(
                    strategy,
                    warmup_candles,
                    symbol,
                    timeframe,
                    context,
                )
            )
            await runtime.event_publisher.persist(warmup_events)
            await runtime.event_publisher.flush()

        return runtime
