from fastapi import FastAPI
from .services.streamer import streamer_manager
import logging

logger = logging.getLogger(__name__)

def setup_data_service(app: FastAPI):
    @app.on_event("startup")
    async def startup_event():
        try:
            await streamer_manager.start()
            logger.info("Data Service started successfully")
        except Exception as e:
            logger.error(f"Failed to start Data Service: {e}")

    @app.on_event("shutdown")
    async def shutdown_event():
        await streamer_manager.stop()
        logger.info("Data Service stopped")
