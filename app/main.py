from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import RedirectResponse

from app.advices.global_exception_handler import GlobalExceptionHandler
from app.modules.user_service.routes.auth_routes import auth_router
from app.modules.user_service.routes.session_routes import session_router
from app.modules.user_service.routes.user_routes import user_router

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
        "https://crypalgos.com",
        "https://www.crypalgos.com"
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


# Include routers
app.include_router(auth_router, prefix="/api/v1")
app.include_router(session_router, prefix="/api/v1")
app.include_router(user_router, prefix="/api/v1")
