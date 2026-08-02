import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import RedirectResponse

from app.advices.global_exception_handler import GlobalExceptionHandler
from app.config.settings import settings
from app.modules.strategy_service.routes.strategy_routes import strategy_router
from app.modules.user_service.routes.auth_routes import auth_router
from app.modules.user_service.routes.contact_routes import contact_router
from app.modules.user_service.routes.session_routes import session_router
from app.modules.user_service.routes.user_routes import user_router

logger = logging.getLogger(__name__)

if settings.app_environment in ("production", "prod", "staging") and not settings.sandbox_enabled:
    # Not a hard fail: infra readiness (Docker + gVisor) for the sandbox is an
    # ops decision this process can't verify. But it must be impossible to
    # silently ship production without it once external users submit strategies.
    logger.critical(
        "SECURITY: app_environment=%s but sandbox_enabled=False — user strategy "
        "code will execute in-process with full credentials. Set "
        "SANDBOX_ENABLED=true (with Docker + gVisor provisioned) before "
        "accepting strategies from untrusted users.",
        settings.app_environment,
    )

app = FastAPI(
    title="CrypAlgos Api Docs",
    description="API documentation for CrypAlgos",
    version="1.0.0",
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:3001",
        "https://crypalgos.com",
        "https://www.crypalgos.com",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register global exception handlers
GlobalExceptionHandler.register_exception_handlers(app)


@app.get("/health", include_in_schema=False)
async def health_check() -> dict[str, str]:
    """Health check endpoint"""
    return {"status": "healthy", "message": "API is running"}


@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> RedirectResponse:
    return RedirectResponse(url="https://crypalgos.com/favicon.ico")


from app.modules.config_service.routes.config_routes import config_router
from app.modules.data_service.routes.market_routes import market_router
from app.modules.replay.routes.replay_routes import replay_router
from app.modules.user_service.routes.credential_routes import credential_router

# Include routers
app.include_router(auth_router, prefix="/api/v1")
app.include_router(session_router, prefix="/api/v1")
app.include_router(user_router, prefix="/api/v1")
app.include_router(contact_router, prefix="/api/v1")
app.include_router(strategy_router, prefix="/api/v1")
app.include_router(credential_router, prefix="/api/v1")
app.include_router(market_router, prefix="/api/v1")
app.include_router(replay_router, prefix="/api/v1")
app.include_router(config_router, prefix="/api/v1")

# Setup live-session Redis -> WebSocket bridge
from app.modules.strategy_service.services.live_event_bridge import (
    setup_live_event_bridge,
)

setup_live_event_bridge(app)
