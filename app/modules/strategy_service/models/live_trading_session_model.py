import uuid
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, Index, String, text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.config.base import Base

if TYPE_CHECKING:
    from app.modules.strategy_service.models.strategy_model import Strategy
    from app.modules.strategy_service.models.strategy_version_model import (
        StrategyVersion,
    )


class SessionEnvironment(StrEnum):
    """Immutable Delta market environment used by execution and replay."""

    TESTNET = "TESTNET"
    PRODUCTION = "PRODUCTION"


class SessionState(StrEnum):
    """Legal transitions:
    STARTING -> RUNNING | ERROR
    RUNNING -> STOPPING | ERROR | RECOVERING
    RECOVERING -> RUNNING | ERROR
    STOPPING -> STOPPED
    ERROR and STOPPED are terminal.
    """

    STARTING = "STARTING"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    ERROR = "ERROR"
    RECOVERING = "RECOVERING"


class LiveTradingSession(Base):
    """Tracks active and historical Live/Paper trading sessions per strategy."""

    __tablename__ = "live_trading_sessions"
    __table_args__ = (
        # DB-level guard: only one RUNNING session allowed per strategy at a time.
        # Partial unique index — only enforces when status = 'RUNNING'.
        Index(
            "uq_strategy_running_session",
            "strategy_id",
            unique=True,
            postgresql_where=text("status = 'RUNNING'"),
        ),
        Index("idx_live_sessions_strategy_status", "strategy_id", "status"),
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
    version_id: Mapped[Optional[str]] = mapped_column(
        String(150),
        ForeignKey("strategy_versions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Execution mode is separate from the immutable market environment.
    mode: Mapped[str] = mapped_column(String(16), nullable=False)  # "LIVE" | "PAPER"
    broker: Mapped[str] = mapped_column(String(32), nullable=False)
    exchange: Mapped[str] = mapped_column(String(32), nullable=False)
    environment: Mapped[SessionEnvironment] = mapped_column(
        SAEnum(SessionEnvironment, name="session_environment"), nullable=False
    )
    symbol: Mapped[str] = mapped_column(String(128), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(16), nullable=False)

    # Which of the user's broker credentials executes this session. Every
    # session requires one: PAPER uses a Delta Testnet credential and LIVE
    # uses a Delta Production credential. A user can hold multiple credentials
    # for the same exchange, so the selected one is immutable session metadata.
    credential_id: Mapped[Optional[str]] = mapped_column(
        String(150),
        ForeignKey("broker_credentials.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Session lifecycle status — see SessionState for legal transitions.
    status: Mapped[SessionState] = mapped_column(
        SAEnum(SessionState, name="session_state"),
        default=SessionState.STARTING,
        nullable=False,
        index=True,
    )

    # Celery task ID for tracking and revoke
    celery_task_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Error details if status = ERROR
    error_msg: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # Heartbeat — updated every N seconds by runner. Used for crash detection.
    heartbeat_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Last processed bar epoch_ms — enables safe resume after crash (RECOVERING).
    last_processed_timestamp: Mapped[Optional[int]] = mapped_column(nullable=True)

    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    stopped_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
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
    strategy: Mapped["Strategy"] = relationship(
        "Strategy", back_populates="live_sessions"
    )
    version: Mapped[Optional["StrategyVersion"]] = relationship(
        "StrategyVersion", back_populates="live_sessions"
    )


# Import here to avoid circular imports during mapper initialization
from app.modules.strategy_service.models.strategy_model import Strategy
from app.modules.strategy_service.models.strategy_version_model import StrategyVersion
