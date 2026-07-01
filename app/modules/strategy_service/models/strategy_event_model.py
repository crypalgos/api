import uuid
from datetime import datetime
from sqlalchemy import JSON, DateTime, String, Index
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from app.config.base import Base

class StrategyEvent(Base):
    __tablename__ = "strategy_events"
    __table_args__ = (
        Index("idx_events_run_type", "strategy_run_id", "event_type"),
    )

    id: Mapped[str] = mapped_column(
        String(150),
        primary_key=True,
        index=True,
        unique=True,
        default=lambda: str(uuid.uuid4()),
    )
    strategy_run_id: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
        index=True
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    event_version: Mapped[str] = mapped_column(String(32), default="1.0", nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
