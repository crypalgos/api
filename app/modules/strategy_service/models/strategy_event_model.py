import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.config.base import Base


class StrategyEvent(Base):
    __tablename__ = "strategy_events"
    __table_args__ = (
        Index("idx_events_run_type", "strategy_run_id", "event_type"),
        Index("idx_events_session_created", "session_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(
        String(150),
        primary_key=True,
        index=True,
        unique=True,
        default=lambda: str(uuid.uuid4()),
    )
    strategy_run_id: Mapped[str] = mapped_column(
        String(150), nullable=False, index=True
    )
    # FK'd counterpart to strategy_run_id, populated only for the durable
    # Celery path (EventPublisher). Nullable because Path B's ExecutionRunner
    # (PersistenceService.persist_event) writes rows with no LiveTradingSession
    # DB row to point at at all — a hard FK on strategy_run_id itself would
    # break that path; this column is additive instead, and is what
    # GET /live-sessions/{id}/timeline (Phase 3) queries against.
    session_id: Mapped[Optional[str]] = mapped_column(
        String(150),
        ForeignKey("live_trading_sessions.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    event_version: Mapped[str] = mapped_column(
        String(32), default="1.0", nullable=False
    )
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
