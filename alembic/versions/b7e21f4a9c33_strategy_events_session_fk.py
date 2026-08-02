"""strategy_events_session_fk

Revision ID: b7e21f4a9c33
Revises: a1c4f9d02b7e
Create Date: 2026-07-19 00:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7e21f4a9c33'
down_revision: Union[str, Sequence[str], None] = 'a1c4f9d02b7e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "strategy_events",
        sa.Column("session_id", sa.String(length=150), nullable=True),
    )
    op.create_index(
        op.f("ix_strategy_events_session_id"),
        "strategy_events",
        ["session_id"],
        unique=False,
    )
    op.create_index(
        "idx_events_session_created",
        "strategy_events",
        ["session_id", "created_at"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_strategy_events_session_id",
        "strategy_events",
        "live_trading_sessions",
        ["session_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        "fk_strategy_events_session_id", "strategy_events", type_="foreignkey"
    )
    op.drop_index("idx_events_session_created", table_name="strategy_events")
    op.drop_index(
        op.f("ix_strategy_events_session_id"), table_name="strategy_events"
    )
    op.drop_column("strategy_events", "session_id")
