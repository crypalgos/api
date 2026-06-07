import uuid
from typing import TYPE_CHECKING, Any, Dict

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.config.base import Base

if TYPE_CHECKING:
    from app.modules.strategy_service.models.strategy_model import Strategy


class Backtest(Base):
    __tablename__ = "backtests"

    id: Mapped[str] = mapped_column(
        String(150),
        primary_key=True,
        index=True,
        unique=True,
        default=lambda: str(uuid.uuid4()),
    )
    strategy_id: Mapped[str] = mapped_column(
        String(150),
        ForeignKey("strategies.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    
    # Backtest configurations
    exchange: Mapped[str] = mapped_column(String(50), nullable=False)
    symbol: Mapped[str] = mapped_column(String(50), nullable=False)
    start_date: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_date: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False)
    initial_capital: Mapped[float] = mapped_column(Float, nullable=False, default=10000.0)
    leverage: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    
    # Serialized performance indicators (win_rate, sharpe_ratio, net_profit, max_drawdown)
    metrics_json: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    
    # 1,000-Point sampled equity/drawdown timelines and trade lists for charting
    charting_json: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    
    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    strategy: Mapped["Strategy"] = relationship("Strategy", back_populates="backtests")
