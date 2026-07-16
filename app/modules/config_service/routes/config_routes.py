from fastapi import APIRouter
from app.modules.config_service.services.config_service import ConfigService

config_router = APIRouter(tags=["Config"])
_config_service = ConfigService()


@config_router.get("/config/registry")
async def get_config_registry() -> dict:
    """Centralized configuration registry for the platform."""
    data = _config_service.get_registry()
    return {"status": "success", "data": data}
