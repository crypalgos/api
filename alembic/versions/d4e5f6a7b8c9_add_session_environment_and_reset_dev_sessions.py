"""Add immutable market metadata and reset development live sessions.

Revision ID: d4e5f6a7b8c9
Revises: c92e6d1487a0
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "c92e6d1487a0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_environment = sa.Enum("TESTNET", "PRODUCTION", name="session_environment")


def upgrade() -> None:
    """Discard pre-launch sessions that lack deterministic environment data."""
    op.execute("DELETE FROM strategy_events WHERE session_id IS NOT NULL")
    op.execute("DELETE FROM live_trading_sessions")
    bind = op.get_bind()
    _environment.create(bind, checkfirst=True)
    op.add_column("live_trading_sessions", sa.Column("exchange", sa.String(32), nullable=False))
    op.add_column("live_trading_sessions", sa.Column("environment", _environment, nullable=False))
    op.add_column("live_trading_sessions", sa.Column("symbol", sa.String(128), nullable=False))
    op.add_column("live_trading_sessions", sa.Column("timeframe", sa.String(16), nullable=False))


def downgrade() -> None:
    """Remove immutable metadata; deleted development sessions cannot be restored."""
    op.drop_column("live_trading_sessions", "timeframe")
    op.drop_column("live_trading_sessions", "symbol")
    op.drop_column("live_trading_sessions", "environment")
    op.drop_column("live_trading_sessions", "exchange")
    _environment.drop(op.get_bind(), checkfirst=True)
