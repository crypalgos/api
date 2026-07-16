import uuid
from typing import TYPE_CHECKING, Any, Dict, List

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.config.base import Base

if TYPE_CHECKING:
    from app.modules.strategy_service.models.research_run_model import (
        ResearchRun,
        StrategyLatestResults,
    )
    from app.modules.strategy_service.models.strategy_version_model import (
        StrategyVersion,
    )
    from app.modules.strategy_service.models.live_trading_session_model import (
        LiveTradingSession,
    )


class Strategy(Base):
    __tablename__ = "strategies"

    id: Mapped[str] = mapped_column(
        String(150),
        primary_key=True,
        index=True,
        unique=True,
        default=lambda: str(uuid.uuid4()),
    )
    user_id: Mapped[str] = mapped_column(
        String(150),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(
        String(255), nullable=True, default=None
    )

    # Declarative visual node/edge JSON dictionary representing React Flow Canvas
    canvas_json: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)

    # Python StrategyBase subclass code
    compiled_code: Mapped[str] = mapped_column(String, nullable=False)

    # State tracking if the user has customized the code in the editor, bypassing automatic canvas compilations
    is_code_modified: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )

    is_template: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    strategy_type: Mapped[str] = mapped_column(
        String(20), default="VISUAL", nullable=False
    )  # VISUAL or CODE
    source_code: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    compiled_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True, default=None
    )
    current_version: Mapped[int] = mapped_column(default=0, nullable=False)
    has_unpublished_changes: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )

    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    research_runs: Mapped[List["ResearchRun"]] = relationship(
        "ResearchRun", back_populates="strategy", cascade="all, delete-orphan"
    )
    latest_results: Mapped["StrategyLatestResults"] = relationship(
        "StrategyLatestResults",
        back_populates="strategy",
        cascade="all, delete-orphan",
        uselist=False,
    )
    versions: Mapped[List["StrategyVersion"]] = relationship(
        "StrategyVersion",
        back_populates="strategy",
        cascade="all, delete-orphan",
        foreign_keys="[StrategyVersion.strategy_id]",
    )
    live_sessions: Mapped[List["LiveTradingSession"]] = relationship(
        "LiveTradingSession",
        back_populates="strategy",
        cascade="all, delete-orphan",
    )

    @property
    def version(self) -> int:
        return self.current_version


# Import here to avoid circular imports during mapper initialization
from app.modules.strategy_service.models.strategy_version_model import StrategyVersion
from app.modules.strategy_service.models.live_trading_session_model import LiveTradingSession
from app.modules.strategy_service.models.research_run_model import ResearchRun
