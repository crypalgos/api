"""
Phase 0 correctness gate — api side (REFACTOR_PLAN.md Part 7):
T-API-1  exchange resolved from strategy graph, never silent delta
T-API-2  summary/exchange metadata comes from the resolved exchange
T-API-3  run_hash covers the compiled code
T-API-5  sandbox payloads survive the JSON boundary
"""
import json
from datetime import datetime, timezone

import numpy as np
import pytest

from app.modules.strategy_service.tasks.task_utils import (
    StrategyRunParams,
    compute_run_hash,
    extract_run_params,
)

START = datetime(2026, 6, 1, tzinfo=timezone.utc)
END = datetime(2026, 6, 20, tzinfo=timezone.utc)


def _strategy_class(exchange=None, datasources=None):
    attrs = {}
    if datasources is not None:
        attrs["datasources"] = datasources
    if exchange is not None:
        attrs["exchange"] = exchange
    return type("FakeStrategy", (), attrs)


# ── T-API-1: exchange resolution ───────────────────────────────────────────

def test_exchange_from_datasources():
    cls = _strategy_class(datasources={
        "btc": {"symbol": "BTCUSD", "timeframe": "1h", "leverage": 3, "exchange": "binance"}
    })
    params = extract_run_params(cls)
    assert params.exchange_name == "binance"
    assert params.symbols == ["BTCUSD"]
    assert params.leverage == 3
    assert params.timeframe == "1h"


def test_exchange_falls_back_to_class_attribute():
    cls = _strategy_class(
        exchange="okx",
        datasources={"btc": {"symbol": "BTCUSD"}},
    )
    assert extract_run_params(cls).exchange_name == "okx"


def test_missing_exchange_raises():
    cls = _strategy_class(datasources={"btc": {"symbol": "BTCUSD"}})
    with pytest.raises(ValueError, match="declares no exchange"):
        extract_run_params(cls)


def test_unknown_exchange_raises():
    cls = _strategy_class(exchange="not-an-exchange")
    with pytest.raises(ValueError, match="Unknown exchange"):
        extract_run_params(cls)


def test_no_silent_delta_default():
    """The old code defaulted exchange_name='delta' — a bare class must error."""
    with pytest.raises(ValueError):
        extract_run_params(_strategy_class())


# ── T-API-3: run_hash covers the code ──────────────────────────────────────

def _hash(code, version_id=None, capital=10000.0):
    return compute_run_hash(
        strategy_version_id=version_id,
        compiled_code=code,
        params=StrategyRunParams(symbols=["BTCUSD"], exchange_name="delta"),
        start_date=START,
        end_date=END,
        initial_capital=capital,
        commission=0.0002,
        slippage=0.0002,
    )


def test_run_hash_differs_for_different_code():
    assert _hash("class A: pass") != _hash("class B: pass")


def test_run_hash_stable_for_identical_inputs():
    assert _hash("class A: pass") == _hash("class A: pass")


def test_run_hash_differs_for_different_inputs():
    assert _hash("class A: pass", capital=10000.0) != _hash("class A: pass", capital=20000.0)


# ── T-API-5: sandbox JSON boundary ─────────────────────────────────────────

def test_sandbox_payload_json_safe():
    """Payloads with datetimes / numpy scalars must survive json.dump(default=str),
    which is what both sandbox boundaries now use."""
    payload = {
        "trades": [{"entry_time": datetime(2026, 6, 1), "pnl": np.float64(12.5)}],
        "counts": np.int64(3),
        "curve": [[np.int64(1), np.float64(2.0)]],
    }
    encoded = json.dumps(payload, default=str)
    decoded = json.loads(encoded)
    assert float(decoded["trades"][0]["pnl"]) == 12.5
    assert decoded["trades"][0]["entry_time"] == "2026-06-01 00:00:00"


def test_sandbox_runner_uses_default_str():
    """Structural guard: the generated runner script must not regress to bare json.dump."""
    import inspect
    from app.modules.strategy_service.tasks import sandbox

    src = inspect.getsource(sandbox)
    assert 'json.dump(report, f, default=str)' in src
