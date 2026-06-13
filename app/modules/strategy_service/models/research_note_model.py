import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.config.base import Base

if TYPE_CHECKING:
    from app.modules.strategy_service.models.research_run_model import ResearchRun
    from app.modules.strategy_service.models.strategy_model import Strategy


class ResearchNote(Base):
    __tablename__ = "research_notes"

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
    run_id: Mapped[str | None] = mapped_column(
        String(150),
        ForeignKey("research_runs.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    strategy: Mapped["Strategy"] = relationship("Strategy")
    run: Mapped[Optional["ResearchRun"]] = relationship("ResearchRun")
