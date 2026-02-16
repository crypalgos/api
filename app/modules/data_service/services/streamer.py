import asyncio
import logging
from .broker import ZMQBroker
from ..clients.delta_client import DeltaExchangeClient

logger = logging.getLogger(__name__)

class StreamerManager:
    def __init__(self):
        self.broker = ZMQBroker()
        self.clients = [
            DeltaExchangeClient(self.broker)
        ]
        self.tasks = []

    async def start(self):
        logger.info("Starting Data Streamer...")
        await self.broker.start()
        
        for client in self.clients:
            task = asyncio.create_task(client.connect())
            self.tasks.append(task)
        
        logger.info("All exchange clients started")

    async def stop(self):
        logger.info("Stopping Data Streamer...")
        for client in self.clients:
            await client.stop()
        
        for task in self.tasks:
            task.cancel()
        
        await self.broker.stop()
        logger.info("Data Streamer stopped")

# Global instance for lifecycle management
streamer_manager = StreamerManager()
