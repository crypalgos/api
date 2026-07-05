"""Typed database summary for backtest runs — replaces ad-hoc summary dicts."""
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from pydantic import BaseModel

if TYPE_CHECKING:
    from app.modules.strategy_service.tasks.task_utils import StrategyRunParams


class RunSummary(BaseModel):
    net_profit: float = 0.0
    total_return_pct: float = 0.0
    sharpe_ratio: Optional[float] = None
    sortino_ratio: Optional[float] = None
    calmar_ratio: Optional[float] = None
    max_drawdown_pct: float = 0.0
    trade_count: int = 0
    win_rate: float = 0.0
    expectancy: Optional[float] = None
    average_trade: Optional[float] = None
    exchange: str
    symbol: str
    start_date: str
    end_date: str
    initial_capital: float
    leverage: int
    equity_preview: List[Any] = []

    @classmethod
    def from_backtest_metrics(
        cls,
        raw_metrics: Dict[str, Any],
        *,
        params: "StrategyRunParams",
        start_date_iso: str,
        end_date_iso: str,
        initial_capital: float,
        equity_preview: List[Any],
    ) -> "RunSummary":
        g = raw_metrics.get("global", raw_metrics.get("global_metrics", raw_metrics))

        total_trades = g.get("total_trades", g.get("trade_count", 0)) or 0
        net_profit = g.get("net_profit", 0.0) or 0.0

        expectancy = g.get("expectancy")
        if expectancy is None:
            expectancy = (
                raw_metrics.get("distributions", {}).get("global", {}).get("expectancy")
            )

        average_trade = g.get("average_trade")
        if average_trade is None:
            average_trade = net_profit / total_trades if total_trades > 0 else 0.0

        return cls(
            net_profit=net_profit,
            total_return_pct=g.get("total_return_pct", 0.0),
            sharpe_ratio=g.get("sharpe_ratio"),
            sortino_ratio=g.get("sortino_ratio"),
            calmar_ratio=g.get("calmar_ratio"),
            max_drawdown_pct=g.get("max_drawdown_pct", 0.0),
            trade_count=total_trades,
            win_rate=g.get("win_rate", 0.0),
            expectancy=expectancy,
            average_trade=average_trade,
            exchange=params.exchange_name,
            symbol=", ".join(params.symbols),
            start_date=start_date_iso,
            end_date=end_date_iso,
            initial_capital=initial_capital,
            leverage=params.leverage,
            equity_preview=equity_preview,
        )
