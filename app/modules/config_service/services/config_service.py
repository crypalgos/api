import copy
import logging
import time
from typing import Any, Dict

from crypalgos_core.compiler.registry import BROKER_REGISTRY, INDICATOR_REGISTRY
from crypalgos_core.database import (
    TIMEFRAME_TO_CLICKHOUSE_INTERVAL,
    get_clickhouse_client,
)

logger = logging.getLogger(__name__)

_CONFIG_CACHE: Dict[str, Any] = {"timestamp": 0, "data": None}
CACHE_TTL = 300  # 5 minutes


class ConfigService:
    """Service responsible for building and caching the platform configuration registry."""

    def get_registry(self) -> dict:
        """Return centralized configuration registry, with 5-minute in-memory cache."""
        current_time = time.time()
        if (
            _CONFIG_CACHE["data"]
            and current_time - _CONFIG_CACHE["timestamp"] < CACHE_TTL
        ):
            return _CONFIG_CACHE["data"]

        dynamic_brokers = copy.deepcopy(BROKER_REGISTRY)
        timeframes = list(TIMEFRAME_TO_CLICKHOUSE_INTERVAL.keys())

        try:
            client = get_clickhouse_client()
            result = client.query(
                "SELECT DISTINCT symbol, exchange FROM crypalogs.ohlcv_1m"
            )
            db_symbols: Dict[str, list] = {}
            for row in result.result_rows:
                sym, exch = str(row[0]), str(row[1])
                if exch not in db_symbols:
                    db_symbols[exch] = []

                clean_sym = (
                    sym.replace("_PERP", "").replace("_SPOT", "").replace("Q", "")
                )
                coin = clean_sym.replace("USD", "").replace("USDT", "").lower()
                if coin == clean_sym.lower():
                    coin = clean_sym.lower()[:3]

                db_symbols[exch].append(
                    {"symbol": sym, "name": clean_sym, "coin": coin}
                )

            for exch, symbols in db_symbols.items():
                if exch in dynamic_brokers:
                    if (
                        "perpetual" in dynamic_brokers[exch]["instruments"]
                        and exch == "delta"
                    ):
                        dynamic_brokers[exch]["instruments"]["perpetual"] = symbols
                    elif "futures" in dynamic_brokers[exch]["instruments"]:
                        dynamic_brokers[exch]["instruments"]["futures"] = symbols
                    else:
                        dynamic_brokers[exch]["instruments"]["spot"] = symbols
        except Exception as e:
            logger.error(f"Failed to fetch dynamic symbols from ClickHouse: {e}")

        data = {
            "indicators": INDICATOR_REGISTRY,
            "brokers": dynamic_brokers,
            "timeframes": timeframes,
            "nodeOutputs": {
                "dataNode": {
                    "dataType": "OHLCV",
                    "fields": [
                        "timestamp_ms",
                        "open",
                        "high",
                        "low",
                        "close",
                        "volume",
                    ],
                }
            },
        }

        _CONFIG_CACHE["data"] = data
        _CONFIG_CACHE["timestamp"] = current_time

        return data
