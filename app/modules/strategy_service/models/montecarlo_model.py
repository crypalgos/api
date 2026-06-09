import uuid
from typing import TYPE_CHECKING, Any, Dict, Optional

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.config.base import Base

if TYPE_CHECKING:
    from app.modules.strategy_service.models.strategy_model import Strategy
    from app.modules.strategy_service.models.backtest_model import Backtest


class MonteCarloRun(Base):
    __tablename__ = "montecarlo_runs"

    id: Mapped[str] = mapped_column(
        String(150), primary_key=True, index=True, unique=True,
        default=lambda: str(uuid.uuid4()),
    )
    user_id: Mapped[str] = mapped_column(String(150), nullable=False, index=True)
    strategy_id: Mapped[str] = mapped_column(
        String(150),
        ForeignKey("strategies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Source backtest linkage (Monte Carlo is read-only — consumes existing backtest trades)
    source_backtest_id: Mapped[str] = mapped_column(
        String(150),
        ForeignKey("backtests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Job config
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    simulation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=10000)
    method: Mapped[str] = mapped_column(String(30), nullable=False, default="BOOTSTRAP")
    random_seed: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Serialized outputs
    summary_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    progress_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    credits_used: Mapped[int] = mapped_column(Integer, nullable=False, default=50)

    started_at: Mapped[Optional[DateTime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[DateTime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    strategy: Mapped["Strategy"] = relationship("Strategy", back_populates="montecarlo_runs")
