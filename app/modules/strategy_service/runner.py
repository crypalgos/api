import asyncio
import logging
from typing import Any, Optional, Type

from crypalgos_core.engine.context import ExecutionContext, ExecutionMode
from crypalgos_core.engine.risk_engine import RiskEngine
from crypalgos_core.engine.strategy_base import StrategyBase
from crypalgos_core.events.engine_bus import EngineEventBus

from app.modules.data_service.live_feed import live_feed_subscriber
from app.modules.strategy_service.execution.broker_compat import resolve_broker_call
from app.modules.strategy_service.execution.tick_sources import parse_ohlcv_tick
from app.modules.strategy_service.execution.trading_runtime import (
    RuntimeFactory,
    TradingRuntime,
)
from app.modules.strategy_service.paper_broker import PaperBroker

logger = logging.getLogger(__name__)


class ExecutionRunner:
    def __init__(
        self,
        strategy_run_id: str,
        user_id: str,
        strategy_class: Type[StrategyBase],
        mode: ExecutionMode = ExecutionMode.PAPER,
        initial_capital: float = 10000.0,
        leverage: int = 1,
        broker_credentials: Optional[Any] = None,
    ):
        self.context = ExecutionContext(
            strategy_run_id=strategy_run_id, user_id=user_id, mode=mode
        )
        self.strategy_class = strategy_class
        self.bus = EngineEventBus()
        self.broker_credentials = broker_credentials

        # Wire up Persistence Service
        try:
            from app.modules.strategy_service.services.persistence_service import (
                PersistenceService,
            )

            def handle_global_event(event):
                asyncio.create_task(PersistenceService.persist_event(event))

            self.bus.subscribe_all(handle_global_event)
        except (ModuleNotFoundError, ImportError):
            logger.warning(
                "PersistenceService not wired: database dependencies missing."
            )

        # Wire up WebSocket broadcast
        try:
            from app.modules.strategy_service.services.websocket_manager import (
                websocket_manager,
            )

            def handle_ws_broadcast(event):
                asyncio.create_task(websocket_manager.broadcast(strategy_run_id, event))

            self.bus.subscribe_all(handle_ws_broadcast)
        except (ModuleNotFoundError, ImportError):
            logger.warning("WebsocketManager not wired: dependencies missing.")

        # Wire up Notification Service
        try:
            from app.modules.notification_service.notification_service import (
                NotificationService,
            )

            def handle_notification_event(event):
                asyncio.create_task(NotificationService.process_event(event))

            self.bus.subscribe_all(handle_notification_event)
        except (ModuleNotFoundError, ImportError):
            logger.warning("NotificationService not wired: dependencies missing.")

        self.risk_engine = RiskEngine(max_leverage=float(leverage))

        # Setup Broker
        if mode == ExecutionMode.PAPER:
            self.broker = PaperBroker(initial_capital=initial_capital)
        elif mode == ExecutionMode.LIVE:
            from app.modules.strategy_service.live_broker import LiveExchangeBroker

            if broker_credentials:
                self.broker = LiveExchangeBroker(
                    api_key=broker_credentials.api_key,
                    api_secret=broker_credentials.api_secret.get_secret_value(),
                    testnet=broker_credentials.is_testnet,
                )
            else:
                self.broker = LiveExchangeBroker(testnet=True)
        else:
            raise ValueError(f"Unsupported execution mode: {mode}")

        # Instantiate strategy
        self.strategy = strategy_class(
            initial_capital=initial_capital,
            leverage=leverage,
            run_id=strategy_run_id,
            event_bus=self.bus,
        )
        self.strategy.is_live = True
        self.is_running = False

        # Same resolution RuntimeFactory.build() uses for Path A — falls back
        # to "1m" for a strategy with no declared datasources/timeframes
        # rather than raising, since Path B has historically tolerated that
        # (unlike Path A, which requires it to pick a tick source).
        try:
            timeframe = RuntimeFactory._resolve_primary_timeframe(strategy_class)
        except ValueError:
            timeframe = "1m"

        # Drives the same TickEngine the durable Celery path (LiveTradingRunner)
        # uses, via TradingRuntime — constructed directly here (not through
        # RuntimeFactory, which builds from a LiveTradingSession DB row that
        # Path A has and Path B doesn't) so both paths run provably identical
        # execution logic during the migration window. Persistence/websocket/
        # notification fan-out stays on self.bus below (unchanged) rather than
        # TradingRuntime's own EventPublisher, to avoid double-writing events.
        # bus=self.bus is the SAME EngineEventBus already passed to the
        # strategy above — required for TickEngine to collect the strategy's
        # own decision-trace events and share one sequence space with them
        # (see TickEngine's docstring). Path B has no IndicatorWarmup wiring
        # yet (RuntimeFactory.build()/Path A only) — indicator VALUES won't
        # update here even though decision-trace events now will; tracked
        # separately, not blocking this fix.
        self.runtime = TradingRuntime(
            strategy=self.strategy,
            broker=self.broker,
            risk_engine=self.risk_engine,
            context=self.context,
            timeframe=timeframe,
            bus=self.bus,
        )

    async def start(self):
        if self.is_running:
            return

        logger.info(f"Starting ExecutionRunner {self.context.strategy_run_id}...")
        self.strategy.initialize()

        # Reconcile state before starting ZMQ feed
        await self.reconcile_state()

        self.is_running = True

        # Subscribe to ZMQ live feeds
        # Legacy ExecutionRunner may represent more than one instrument, so it
        # remains an explicit all-symbol subscriber. LiveTradingRunner uses
        # the symbol-keyed provider path instead.
        live_feed_subscriber.register_global_callback(self.on_market_tick)
        await live_feed_subscriber.start()

    async def stop(self):
        self.is_running = False
        live_feed_subscriber.unregister_global_callback(self.on_market_tick)
        logger.info(f"ExecutionRunner {self.context.strategy_run_id} stopped.")

    async def reconcile_state(self) -> None:
        """Query the broker for latest balances and positions to reconcile local strategy state."""
        try:
            balances = await resolve_broker_call(self.broker.get_balances())
            logger.info(f"Reconciled runner balances: {balances}")
            if hasattr(self.strategy, "portfolio_engine"):
                pe = self.strategy.portfolio_engine
                pe.portfolio.cash = balances.get("cash", pe.portfolio.cash)
                pe.portfolio.equity = balances.get("equity", pe.portfolio.equity)
        except Exception as e:
            logger.error(f"Failed to reconcile state with broker: {e}")

    async def on_market_tick(self, topic: str, data: Any):
        if not self.is_running:
            return

        bar_event = parse_ohlcv_tick(topic, data)
        if bar_event is None:
            return

        try:
            # TickEngine drives strategy -> risk check -> broker and returns
            # typed events; called directly (not via runtime.tick()) so this
            # runner's own persistence/websocket/notification wiring below
            # remains the single place those events are published, matching
            # today's behavior.
            events = await self.runtime.tick_engine.process_bar(bar_event)
        except Exception as e:
            logger.error(f"ExecutionRunner runtime exception: {e}")
            return

        for event in events:
            try:
                self.bus.publish(event)
            except Exception:
                logger.exception(
                    f"ExecutionRunner failed to publish {type(event).__name__} to bus"
                )
