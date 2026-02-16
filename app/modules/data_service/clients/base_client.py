import abc
import asyncio
import logging
import websockets
import json
from ..services.broker import ZMQBroker

logger = logging.getLogger(__name__)

class BaseExchangeClient(abc.ABC):
    def __init__(self, broker: ZMQBroker, exchange_name: str, ws_url: str):
        self.broker = broker
        self.exchange_name = exchange_name
        self.ws_url = ws_url
        self.ws = None
        self.is_running = False

    @abc.abstractmethod
    def get_subscription_payload(self) -> dict:
        """Returns the payload to subscribe to specific channels"""
        pass

    @abc.abstractmethod
    def normalize_message(self, message: dict) -> dict:
        """Normalizes the exchange-specific message to a unified format"""
        pass

    async def connect(self):
        self.is_running = True
        while self.is_running:
            try:
                logger.info(f"Connecting to {self.exchange_name} WebSocket...")
                async with websockets.connect(self.ws_url) as websocket:
                    self.ws = websocket
                    await self.ws.send(json.dumps(self.get_subscription_payload()))
                    logger.info(f"Subscribed to {self.exchange_name} channels")
                    
                    async for message in websocket:
                        data = json.loads(message)
                        updates = self.normalize_message(data)
                        if updates:
                            # updates can be a single dict, a single tuple, or a list of tuples
                            if isinstance(updates, dict):
                                updates = [("trades", updates)]
                            elif isinstance(updates, tuple):
                                updates = [updates]
                            
                            for topic_suffix, normalized_data in updates:
                                await self.broker.publish(
                                    topic=f"{topic_suffix}.{self.exchange_name}",
                                    data=json.dumps(normalized_data)
                                )
            except Exception as e:
                logger.error(f"Error in {self.exchange_name} connection: {e}")
                if self.is_running:
                    await asyncio.sleep(5)  # Reconnect delay

    async def stop(self):
        self.is_running = False
        if self.ws:
            await self.ws.close()
