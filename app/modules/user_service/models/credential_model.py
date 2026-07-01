import uuid
from datetime import datetime
from enum import Enum
from sqlalchemy import DateTime, ForeignKey, String, Integer, Boolean, Enum as SQLEnum, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from app.config.base import Base

class Exchange(str, Enum):
    DELTA = "delta"
    BINANCE = "binance"
    BYBIT = "bybit"
    OKX = "okx"

class BrokerCredential(Base):
    __tablename__ = "broker_credentials"

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
        index=True
    )
    exchange: Mapped[Exchange] = mapped_column(SQLEnum(Exchange), nullable=False)
    account_label: Mapped[str] = mapped_column(String(100), nullable=False)
    api_key_encrypted: Mapped[str] = mapped_column(String(512), nullable=False)
    api_secret_encrypted: Mapped[str] = mapped_column(String(512), nullable=False)
    passphrase_encrypted: Mapped[str | None] = mapped_column(String(512), nullable=True, default=None)
    
    is_testnet: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True, default=None)
    
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("user_id", "exchange", "account_label", name="uq_user_exchange_label"),
    )

class NotificationPreference(Base):
    __tablename__ = "notification_preferences"

    user_id: Mapped[str] = mapped_column(
        String(150),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
        unique=True
    )
    telegram_chat_id: Mapped[str | None] = mapped_column(String(100), nullable=True, default=None)
    telegram_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    timezone: Mapped[str] = mapped_column(String(50), default="UTC", nullable=False)
    
    paper_alerts: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    live_alerts: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    stoploss_alerts: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    tp_alerts: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

class CredentialAuditLog(Base):
    __tablename__ = "credential_audit_logs"

    id: Mapped[str] = mapped_column(
        String(150),
        primary_key=True,
        index=True,
        unique=True,
        default=lambda: str(uuid.uuid4()),
    )
    user_id: Mapped[str] = mapped_column(String(150), nullable=False, index=True)
    credential_id: Mapped[str | None] = mapped_column(String(150), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)  # e.g., CREATE, UPDATE, DELETE, ROTATE, VERIFY
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
