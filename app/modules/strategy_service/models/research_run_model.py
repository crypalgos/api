import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, Optional

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.config.base import Base

if TYPE_CHECKING:
    from app.modules.strategy_service.models.strategy_model import Strategy
    from app.modules.strategy_service.models.strategy_version_model import (
        StrategyVersion,
    )



class ResearchRun(Base):
    __tablename__ = "research_runs"
    __table_args__ = (
        Index("idx_runs_strat_type_created", "strategy_id", "run_type", "created_at"),
        Index("idx_runs_status", "status"),
        Index("idx_runs_strat_fav", "strategy_id", "is_favorite"),
    )

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
    run_type: Mapped[str] = mapped_column(String(32), nullable=False)  # BACKTEST, OPTIMIZATION, WALKFORWARD, MONTECARLO
    run_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    artifact_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    compiled_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    strategy_version_id: Mapped[str | None] = mapped_column(
        String(150),
        ForeignKey("strategy_versions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    is_favorite: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="PENDING", nullable=False)
    progress_percent: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    progress_json: Mapped[Dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    report_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    
    metadata_s3_key: Mapped[str | None] = mapped_column(String, nullable=True)
    report_s3_key: Mapped[str | None] = mapped_column(String, nullable=True)
    dataset_s3_key: Mapped[str | None] = mapped_column(String, nullable=True)
    
    summary_json: Mapped[Dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    strategy: Mapped["Strategy"] = relationship("Strategy", back_populates="research_runs")
    strategy_version: Mapped[Optional["StrategyVersion"]] = relationship("StrategyVersion", back_populates="research_runs")
    parent_run_id: Mapped[str | None] = mapped_column(
        String(150),
        ForeignKey("research_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    parent_run: Mapped[Optional["ResearchRun"]] = relationship("ResearchRun", remote_side=[id])



# Import here to avoid circular imports during mapper initialization
from app.modules.strategy_service.models.strategy_version_model import StrategyVersion


class StrategyLatestResults(Base):
    __tablename__ = "strategy_latest_results"

    strategy_id: Mapped[str] = mapped_column(
        String(150),
        ForeignKey("strategies.id", ondelete="CASCADE"),
        primary_key=True,
    )
    latest_backtest_id: Mapped[str | None] = mapped_column(
        String(150),
        ForeignKey("research_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    latest_optimization_id: Mapped[str | None] = mapped_column(
        String(150),
        ForeignKey("research_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    latest_walkforward_id: Mapped[str | None] = mapped_column(
        String(150),
        ForeignKey("research_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    latest_montecarlo_id: Mapped[str | None] = mapped_column(
        String(150),
        ForeignKey("research_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    strategy: Mapped["Strategy"] = relationship("Strategy", back_populates="latest_results")
    latest_backtest: Mapped[Optional[ResearchRun]] = relationship(
        "ResearchRun", foreign_keys=[latest_backtest_id]
    )
    latest_optimization: Mapped[Optional[ResearchRun]] = relationship(
        "ResearchRun", foreign_keys=[latest_optimization_id]
    )
    latest_walkforward: Mapped[Optional[ResearchRun]] = relationship(
        "ResearchRun", foreign_keys=[latest_walkforward_id]
    )
    latest_montecarlo: Mapped[Optional[ResearchRun]] = relationship(
        "ResearchRun", foreign_keys=[latest_montecarlo_id]
    )
