from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import RedirectResponse

from app.advices.global_exception_handler import GlobalExceptionHandler
from app.modules.user_service.routes.auth_routes import auth_router
from app.modules.user_service.routes.session_routes import session_router
from app.modules.user_service.routes.user_routes import user_router
from app.modules.user_service.routes.contact_routes import contact_router
from app.modules.strategy_service.routes.strategy_routes import strategy_router

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


from crypalgos_core.compiler.registry import INDICATOR_REGISTRY, BROKER_REGISTRY
from crypalgos_core.database import get_clickhouse_client, TIMEFRAME_TO_CLICKHOUSE_INTERVAL
import time
import copy
from typing import Dict, Any
import logging

_CONFIG_CACHE: Dict[str, Any] = {"timestamp": 0, "data": None}
CACHE_TTL = 300  # 5 minutes

@app.get("/api/v1/config/registry")
async def get_config_registry() -> dict:
    """Centralized configuration registry for the platform"""
    current_time = time.time()
    if _CONFIG_CACHE["data"] and current_time - _CONFIG_CACHE["timestamp"] < CACHE_TTL:
        return {"status": "success", "data": _CONFIG_CACHE["data"]}
        
    dynamic_brokers = copy.deepcopy(BROKER_REGISTRY)
    timeframes = list(TIMEFRAME_TO_CLICKHOUSE_INTERVAL.keys())
    
    try:
        client = get_clickhouse_client()
        result = client.query("SELECT DISTINCT symbol, exchange FROM crypalogs.ohlcv_1m")
        db_symbols = {}
        for row in result.result_rows:
            sym, exch = str(row[0]), str(row[1])
            if exch not in db_symbols:
                db_symbols[exch] = []
            
            clean_sym = sym.replace("_PERP", "").replace("_SPOT", "").replace("Q", "")
            coin = clean_sym.replace("USD", "").replace("USDT", "").lower()
            if coin == clean_sym.lower():
                coin = clean_sym.lower()[:3]
                
            db_symbols[exch].append({
                "symbol": sym,
                "name": clean_sym,
                "coin": coin
            })
            
        for exch, symbols in db_symbols.items():
            if exch in dynamic_brokers:
                # If Delta Exchange has perpetual supported, prioritize placing them there
                if 'perpetual' in dynamic_brokers[exch]['instruments'] and exch == 'delta':
                    dynamic_brokers[exch]['instruments']['perpetual'] = symbols
                elif 'futures' in dynamic_brokers[exch]['instruments']:
                    dynamic_brokers[exch]['instruments']['futures'] = symbols
                else:
                    dynamic_brokers[exch]['instruments']['spot'] = symbols
    except Exception as e:
        logging.getLogger("API").error(f"Failed to fetch dynamic symbols from ClickHouse: {e}")
    
    data = {
        "indicators": INDICATOR_REGISTRY,
        "brokers": dynamic_brokers,
        "timeframes": timeframes,
        "nodeOutputs": {
            "dataNode": {
                "dataType": "OHLCV",
                "fields": ["timestamp_ms", "open", "high", "low", "close", "volume"]
            }
        }
    }
    
    _CONFIG_CACHE["data"] = data
    _CONFIG_CACHE["timestamp"] = current_time
    
    return {
        "status": "success",
        "data": data
    }


@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> RedirectResponse:
    return RedirectResponse(url="https://crypalgos.com/favicon.ico")


# Include routers
app.include_router(auth_router, prefix="/api/v1")
app.include_router(session_router, prefix="/api/v1")
app.include_router(user_router, prefix="/api/v1")
app.include_router(contact_router, prefix="/api/v1")
app.include_router(strategy_router, prefix="/api/v1")

# Setup Data Service
from app.modules.data_service.manager import setup_data_service
setup_data_service(app)
