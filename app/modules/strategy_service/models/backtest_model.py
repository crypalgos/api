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
    start_date: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_date: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False)
    initial_capital: Mapped[float] = mapped_column(Float, nullable=False, default=10000.0)
    
    # Status tracking (PENDING, RUNNING, COMPLETED, FAILED)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    
    # Serialized performance indicators (win_rate, sharpe_ratio, net_profit, max_drawdown)
    metrics_json: Mapped[Dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    
    # Serialized charting arrays (equity_curve, drawdown_curve, trades)
    charting_json: Mapped[Dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    progress_json: Mapped[Dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    credits_used: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    
    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    strategy: Mapped["Strategy"] = relationship("Strategy", back_populates="backtests")
