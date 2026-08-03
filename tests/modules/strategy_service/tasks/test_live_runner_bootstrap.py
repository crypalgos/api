"""Regression tests for LiveTradingRunner._bootstrap().

Two real, previously-dormant bugs made every Path A bootstrap fail before
ever reaching _tick():
  1. `from app.db.connect_db import get_sync_session` — that name has never
     existed in connect_db.py (only AsyncSessionLocal/get_db do), so every
     DB-touching method raised ImportError.
  2. `credential_service.get_broker_credentials(user_id, broker=...)` — that
     method has never existed either; the real one is
     get_decrypted_broker_credential(credential_id), which needs a
     credential_id the LiveTradingSession model didn't even have a column
     for until this phase.

These tests exercise the fixed _bootstrap() against mocks, proving it now
reaches RuntimeFactory.build() and selects the right tick source, without
needing a real Postgres/Redis/Celery/testnet account.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import SecretStr

import app.db.connect_db as connect_db_mod
import app.modules.strategy_service.repositories.live_trading_session_repository as repo_mod
import app.modules.user_service.services.credential_service as cred_mod
from app.modules.strategy_service.execution.tick_sources import (
    DeltaMainnetTickSource,
    DeltaTestnetTickSource,
)
from app.modules.strategy_service.models.live_trading_session_model import (
    SessionEnvironment,
)
from app.modules.strategy_service.tasks.live_runner import LiveTradingRunner
from app.modules.strategy_service.utils.event_bus import EventBus
from app.modules.user_service.models.credential_model import Exchange
from app.modules.user_service.services.credential_service import BrokerCredentials

COMPILED_CODE = """
from crypalgos_core.engine.strategy_base import StrategyBase

class _T(StrategyBase):
    exchange = "delta"
    datasources = {"btcusd": {"symbol": "BTCUSD", "leverage": 1, "timeframes": ["1h"]}}
    def initialize(self): pass
    def on_event(self, event): pass
"""


def _fake_session(mode: str, credential_id: str | None) -> SimpleNamespace:
    strategy = SimpleNamespace(user_id="user-1", compiled_code=COMPILED_CODE)
    return SimpleNamespace(
        id="sess-1",
        strategy_id="strat-1",
        mode=mode,
        broker="delta",
        exchange="delta",
        environment=(
            SessionEnvironment.TESTNET
            if mode == "PAPER"
            else SessionEnvironment.PRODUCTION
        ),
        symbol="BTCUSD",
        timeframe="1h",
        credential_id=credential_id,
        strategy=strategy,
        version=None,
    )


class _MockAsyncSessionCtx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        pass


def _patch_db_session(monkeypatch):
    monkeypatch.setattr(connect_db_mod, "AsyncSessionLocal", lambda: _MockAsyncSessionCtx())


async def test_bootstrap_uses_testnet_market_data_for_paper_sessions(
    monkeypatch,
) -> None:
    _patch_db_session(monkeypatch)

    session = _fake_session(mode="PAPER", credential_id="cred-1")

    class FakeRepo:
        def __init__(self, db_session):
            pass

        async def get_by_id_with_relations(self, session_id):
            assert session_id == "sess-1"
            return session

    monkeypatch.setattr(repo_mod, "LiveTradingSessionRepository", FakeRepo)

    get_cred = AsyncMock(
        return_value=BrokerCredentials(
            id="cred-1",
            exchange=Exchange.DELTA,
            api_key="k",
            api_secret=SecretStr("s"),
            is_testnet=True,
        )
    )
    monkeypatch.setattr(cred_mod.credential_service, "get_decrypted_broker_credential", get_cred)

    runner = LiveTradingRunner(session_id="sess-1", event_bus=EventBus())
    await runner._bootstrap()

    get_cred.assert_awaited_once_with("cred-1")
    assert runner._runtime is not None
    assert runner._runtime.symbol == "BTCUSD"
    assert isinstance(runner._tick_source, DeltaTestnetTickSource)


async def test_bootstrap_picks_mainnet_source_when_credential_is_not_testnet(
    monkeypatch,
) -> None:
    _patch_db_session(monkeypatch)

    session = _fake_session(mode="LIVE", credential_id="cred-2")

    class FakeRepo:
        def __init__(self, db_session):
            pass

        async def get_by_id_with_relations(self, session_id):
            return session

    monkeypatch.setattr(repo_mod, "LiveTradingSessionRepository", FakeRepo)

    get_cred = AsyncMock(
        return_value=BrokerCredentials(
            id="cred-2",
            exchange=Exchange.DELTA,
            api_key="k",
            api_secret=SecretStr("s"),
            is_testnet=False,
        )
    )
    monkeypatch.setattr(cred_mod.credential_service, "get_decrypted_broker_credential", get_cred)

    runner = LiveTradingRunner(session_id="sess-1", event_bus=EventBus())
    await runner._bootstrap()

    assert isinstance(runner._tick_source, DeltaMainnetTickSource)


async def test_bootstrap_rejects_live_mode_without_credential_id(monkeypatch) -> None:
    _patch_db_session(monkeypatch)

    session = _fake_session(mode="LIVE", credential_id=None)

    class FakeRepo:
        def __init__(self, db_session):
            pass

        async def get_by_id_with_relations(self, session_id):
            return session

    monkeypatch.setattr(repo_mod, "LiveTradingSessionRepository", FakeRepo)

    runner = LiveTradingRunner(session_id="sess-1", event_bus=EventBus())
    with pytest.raises(RuntimeError, match="credential_id"):
        await runner._bootstrap()


async def test_bootstrap_rejects_unsupported_broker(monkeypatch) -> None:
    _patch_db_session(monkeypatch)

    session = _fake_session(mode="PAPER", credential_id=None)
    session.broker = "binance"

    class FakeRepo:
        def __init__(self, db_session):
            pass

        async def get_by_id_with_relations(self, session_id):
            return session

    monkeypatch.setattr(repo_mod, "LiveTradingSessionRepository", FakeRepo)

    runner = LiveTradingRunner(session_id="sess-1", event_bus=EventBus())
    with pytest.raises(RuntimeError, match="Unsupported broker"):
        await runner._bootstrap()
