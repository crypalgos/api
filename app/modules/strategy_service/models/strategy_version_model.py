import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.config.base import Base

if TYPE_CHECKING:
    from app.modules.strategy_service.models.research_run_model import ResearchRun
    from app.modules.strategy_service.models.strategy_model import Strategy


class StrategyVersion(Base):
    __tablename__ = "strategy_versions"
    __table_args__ = (
        Index("idx_strategy_versions_strat_ver", "strategy_id", "version", unique=True),
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
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    commit_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    canvas_json: Mapped[Dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    source_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    compiled_code: Mapped[str] = mapped_column(Text, nullable=False)
    compiled_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    is_code_modified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    approval_status: Mapped[str] = mapped_column(String(32), default="DRAFT", nullable=False)
    is_golden: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


    # Relationships
    strategy: Mapped["Strategy"] = relationship("Strategy", back_populates="versions", foreign_keys=[strategy_id])
    research_runs: Mapped[list["ResearchRun"]] = relationship(
        "ResearchRun", back_populates="strategy_version", cascade="all, delete-orphan"
    )
