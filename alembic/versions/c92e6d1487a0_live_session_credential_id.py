"""live_session_credential_id

Revision ID: c92e6d1487a0
Revises: b7e21f4a9c33
Create Date: 2026-07-19 00:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c92e6d1487a0'
down_revision: Union[str, Sequence[str], None] = 'b7e21f4a9c33'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "live_trading_sessions",
        sa.Column("credential_id", sa.String(length=150), nullable=True),
    )
    op.create_index(
        op.f("ix_live_trading_sessions_credential_id"),
        "live_trading_sessions",
        ["credential_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_live_trading_sessions_credential_id",
        "live_trading_sessions",
        "broker_credentials",
        ["credential_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        "fk_live_trading_sessions_credential_id",
        "live_trading_sessions",
        type_="foreignkey",
    )
    op.drop_index(
        op.f("ix_live_trading_sessions_credential_id"),
        table_name="live_trading_sessions",
    )
    op.drop_column("live_trading_sessions", "credential_id")
