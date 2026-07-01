import asyncio
import json
import logging
import zmq
import zmq.asyncio

logger = logging.getLogger(__name__)

class LiveFeedSubscriber:
    def __init__(self, address: str = "ipc:///tmp/data_streamer.ipc"):
        self.address = address
        self.context = zmq.asyncio.Context()
        self.socket = self.context.socket(zmq.SUB)
        self.callbacks = []
        self.task = None
        self.is_running = False

    def register_callback(self, callback):
        """Register a callback that receives (topic, data_dict)."""
        self.callbacks.append(callback)

    def unregister_callback(self, callback):
        if callback in self.callbacks:
            self.callbacks.remove(callback)

    async def start(self):
        if self.is_running:
            return
            
        logger.info(f"Connecting LiveFeedSubscriber to ZMQ at {self.address}...")
        self.socket.connect(self.address)
        # Subscribe to all topics
        self.socket.setsockopt_string(zmq.SUBSCRIBE, "")
        self.is_running = True
        self.task = asyncio.create_task(self._recv_loop())

    async def _recv_loop(self):
        while self.is_running:
            try:
                topic_bytes, data_bytes = await self.socket.recv_multipart()
                topic = topic_bytes.decode("utf-8")
                data_str = data_bytes.decode("utf-8")
                
                try:
                    data = json.loads(data_str)
                except Exception:
                    data = data_str
                    
                for cb in self.callbacks:
                    try:
                        if asyncio.iscoroutinefunction(cb):
                            await cb(topic, data)
                        else:
                            cb(topic, data)
                    except Exception as e:
                        logger.error(f"Error in live feed callback: {e}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in LiveFeed recv loop: {e}")
                await asyncio.sleep(1)

    async def stop(self):
        self.is_running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        self.socket.close()
        self.context.term()
        logger.info("LiveFeedSubscriber stopped")

# Global singleton
live_feed_subscriber = LiveFeedSubscriber()
