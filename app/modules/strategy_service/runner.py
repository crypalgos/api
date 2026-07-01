import asyncio
import logging
from typing import Type, Dict, Any, Optional
from crypalgos_core.engine.strategy_base import StrategyBase
from crypalgos_core.engine.context import ExecutionContext, ExecutionMode
from crypalgos_core.engine.risk_engine import RiskEngine
from crypalgos_core.events.engine_bus import EngineEventBus
from crypalgos_core.events.engine_events import (
    OrderSubmittedEvent, OrderFilledEvent, PositionOpenedEvent, PositionClosedEvent
)
from app.modules.data_service.live_feed import live_feed_subscriber
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
        broker_credentials: Optional[Any] = None
    ):
        self.context = ExecutionContext(
            strategy_run_id=strategy_run_id,
            user_id=user_id,
            mode=mode
        )
        self.strategy_class = strategy_class
        self.bus = EngineEventBus()
        self.broker_credentials = broker_credentials
        
        # Wire up Persistence Service
        try:
            from app.modules.strategy_service.services.persistence_service import PersistenceService
            def handle_global_event(event):
                asyncio.create_task(PersistenceService.persist_event(event))
            self.bus.subscribe_all(handle_global_event)
        except (ModuleNotFoundError, ImportError):
            logger.warning("PersistenceService not wired: database dependencies missing.")
            
        # Wire up WebSocket broadcast
        try:
            from app.modules.strategy_service.services.websocket_manager import websocket_manager
            def handle_ws_broadcast(event):
                asyncio.create_task(websocket_manager.broadcast(strategy_run_id, event))
            self.bus.subscribe_all(handle_ws_broadcast)
        except (ModuleNotFoundError, ImportError):
            logger.warning("WebsocketManager not wired: dependencies missing.")
            
        # Wire up Notification Service
        try:
            from app.modules.notification_service.notification_service import NotificationService
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
                    testnet=broker_credentials.is_testnet
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
            event_bus=self.bus
        )
        self.strategy.is_live = True
        self.is_running = False

    async def start(self):
        if self.is_running:
            return
            
        logger.info(f"Starting ExecutionRunner {self.context.strategy_run_id}...")
        self.strategy.initialize()
        
        # Reconcile state before starting ZMQ feed
        await self.reconcile_state()
        
        self.is_running = True
        
        # Subscribe to ZMQ live feeds
        live_feed_subscriber.register_callback(self.on_market_tick)
        await live_feed_subscriber.start()

    async def stop(self):
        self.is_running = False
        live_feed_subscriber.unregister_callback(self.on_market_tick)
        logger.info(f"ExecutionRunner {self.context.strategy_run_id} stopped.")

    async def reconcile_state(self) -> None:
        """Query the broker for latest balances and positions to reconcile local strategy state."""
        try:
            balances = await self.broker.get_balances()
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
            
        # Delta data streamer publishes ohlcv data under topic: 'ohlcv:<symbol>'
        if topic.startswith("ohlcv:"):
            symbol = topic.split(":")[-1]
            
            # Format candle data for Strategy context
            # schema: timestamp, open, high, low, close, volume
            candle_arr = [
                data.get("timestamp"),
                data.get("open"),
                data.get("high"),
                data.get("low"),
                data.get("close"),
                data.get("volume")
            ]
            
            # Feed current candle into strategy
            self.strategy._current_time = data.get("timestamp")
            self.strategy._current_candle = candle_arr
            
            # Update Broker pricing to value open positions accurately
            if hasattr(self.broker, "update_mark_price"):
                self.broker.update_mark_price(symbol, data.get("close"))
                
            # Create a mock Event for Strategy base on_event handler
            from crypalgos_core.events import Event, EventType
            bar_event = Event(
                type=EventType.BAR,
                timestamp=self.strategy._current_time,
                symbol=symbol,
                data={"candle": candle_arr}
            )
            
            try:
                # Trigger strategy logic
                self.strategy.on_event(bar_event)
                
                # Fetch emitted OrderIntents
                intents = self.strategy.get_and_clear_intents()
                for intent in intents:
                    # Retrieve current position state
                    pos = self.broker.get_position(intent.symbol)
                    pos_qty = pos.get("qty", 0.0) if pos.get("side") == "LONG" else -pos.get("qty", 0.0)
                    
                    # Risk Engine validation check
                    self.risk_engine.evaluate_intent(
                        intent,
                        current_position_size=pos_qty,
                        current_leverage=float(self.strategy.leverage)
                    )
                    
                    # Broker order submission
                    receipt = self.broker.submit_order(
                        symbol=intent.symbol,
                        side=intent.side,
                        qty=intent.qty,
                        price=intent.price,
                        order_type=intent.order_type
                    )
                    
                    # Fire Events on filled
                    seq = self.bus.next_sequence()
                    if receipt.status == "FILLED":
                        # Publish OrderFilledEvent
                        self.bus.publish(OrderFilledEvent(
                            sequence_number=seq,
                            timestamp=int(receipt.timestamp * 1000),
                            symbol_id=intent.symbol,
                            order_id=receipt.order_id,
                            side=intent.side,
                            fill_price=receipt.average_price,
                            fill_quantity=receipt.filled_qty,
                            fee=0.0,
                            context=self.context
                        ))
            except Exception as e:
                logger.error(f"ExecutionRunner runtime exception: {e}")
