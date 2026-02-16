import zmq
import zmq.asyncio
import logging
import asyncio

logger = logging.getLogger(__name__)

class ZMQBroker:
    def __init__(self, address: str = "ipc:///tmp/data_streamer.ipc"):
        self.address = address
        self.context = zmq.asyncio.Context()
        self.socket = self.context.socket(zmq.PUB)
        self.is_running = False

    async def start(self):
        try:
            self.socket.bind(self.address)
            self.is_running = True
            logger.info(f"ZMQ Broker started at {self.address}")
        except Exception as e:
            logger.error(f"Failed to start ZMQ Broker: {e}")
            raise

    async def publish(self, topic: str, data: str):
        if not self.is_running:
            return
        
        try:
            await self.socket.send_multipart([
                topic.encode("utf-8"),
                data.encode("utf-8")
            ])
        except Exception as e:
            logger.error(f"Error publishing to ZMQ: {e}")

    async def stop(self):
        self.is_running = False
        self.socket.close()
        self.context.term()
        logger.info("ZMQ Broker stopped")
