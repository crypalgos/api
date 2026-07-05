"""
Phase 4 gate — api side:
T-DRY-5  RunSummary typed model (no ad-hoc summary dicts)
T-DRY-6  ArtifactPaths single source for S3 key layout
A8       no deprecated datetime.utcnow anywhere in app/
"""
import subprocess
import sys
from pathlib import Path

from app.modules.strategy_service.schemas.run_summary_schema import RunSummary
from app.modules.strategy_service.tasks.task_utils import StrategyRunParams
from app.utils.artifact_paths import ArtifactPaths
from app.utils.time_utils import now_utc

APP_DIR = Path(__file__).resolve().parents[3] / "app"


# ── T-DRY-6: ArtifactPaths ──────────────────────────────────────────────────

def test_artifact_paths_layout():
    paths = ArtifactPaths(strategy_id="s1", run_id="r1", kind="backtests")
    assert paths.metadata == "research/s1/backtests/r1/metadata.msgpack.zstd"
    assert paths.report == "research/s1/backtests/r1/report.msgpack.zstd"
    assert paths.workspace == "research/s1/backtests/r1/workspace.tar.zstd"
    assert paths.runtime == "research/s1/backtests/r1/runtime.arrow.zstd"
    assert paths.decision == "research/s1/backtests/r1/decision.arrow.zstd"

    # Other run kinds preserve their existing (pre-ArtifactPaths) layouts
    assert ArtifactPaths("s1", "r1", "optimization").metadata == (
        "research/s1/optimization/r1/metadata.msgpack.zstd"
    )


def test_no_inline_research_keys():
    """No task/service builds research/... keys by hand anymore."""
    offenders = []
    for py in APP_DIR.rglob("*.py"):
        if py.name == "artifact_paths.py":
            continue
        if 'f"research/' in py.read_text() or "f'research/" in py.read_text():
            offenders.append(str(py))
    assert not offenders, f"inline research/ keys found: {offenders}"


# ── T-DRY-5: RunSummary ─────────────────────────────────────────────────────

def _params():
    return StrategyRunParams(symbols=["BTCUSD", "ETHUSD"], leverage=3, exchange_name="binance")


def test_run_summary_from_metrics():
    raw = {"global": {
        "net_profit": 120.5, "total_return_pct": 1.2, "sharpe_ratio": 1.4,
        "max_drawdown_pct": 3.3, "total_trades": 10, "win_rate": 60.0,
        "expectancy": 12.05,
    }}
    summary = RunSummary.from_backtest_metrics(
        raw, params=_params(), start_date_iso="2026-06-01", end_date_iso="2026-06-20",
        initial_capital=10000.0, equity_preview=[[1, 10000.0]],
    )
    assert summary.net_profit == 120.5
    assert summary.trade_count == 10
    assert summary.exchange == "binance"
    assert summary.symbol == "BTCUSD, ETHUSD"
    assert summary.leverage == 3
    assert summary.equity_preview == [[1, 10000.0]]


def test_run_summary_derives_average_trade():
    raw = {"global": {"net_profit": 100.0, "total_trades": 4}}
    summary = RunSummary.from_backtest_metrics(
        raw, params=_params(), start_date_iso="a", end_date_iso="b",
        initial_capital=1.0, equity_preview=[],
    )
    assert summary.average_trade == 25.0
    assert summary.sharpe_ratio is None  # absent stays None, never fabricated


# ── A8: utcnow eradicated ───────────────────────────────────────────────────

def test_no_datetime_utcnow_in_app():
    offenders = [
        str(py) for py in APP_DIR.rglob("*.py")
        if "datetime.utcnow(" in py.read_text() and py.name != "time_utils.py"
    ]
    assert not offenders, f"deprecated datetime.utcnow in: {offenders}"


def test_now_utc_is_aware():
    assert now_utc().tzinfo is not None
