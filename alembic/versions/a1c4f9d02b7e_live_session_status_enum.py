"""live_session_status_enum

Revision ID: a1c4f9d02b7e
Revises: d3a7296a3537
Create Date: 2026-07-19 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1c4f9d02b7e'
down_revision: Union[str, Sequence[str], None] = 'd3a7296a3537'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SESSION_STATE_VALUES = (
    "STARTING",
    "RUNNING",
    "STOPPING",
    "STOPPED",
    "ERROR",
    "RECOVERING",
)


def upgrade() -> None:
    """Upgrade schema."""
    session_state = sa.Enum(*SESSION_STATE_VALUES, name="session_state")
    session_state.create(op.get_bind(), checkfirst=True)
    
    # Drop partial index before altering column type
    op.drop_index("uq_strategy_running_session", table_name="live_trading_sessions")
    
    op.alter_column(
        "live_trading_sessions",
        "status",
        existing_type=sa.String(length=32),
        type_=session_state,
        postgresql_using="status::text::session_state",
        server_default="STARTING",
        existing_nullable=False,
    )
    
    # Recreate partial index
    op.create_index(
        "uq_strategy_running_session",
        "live_trading_sessions",
        ["strategy_id"],
        unique=True,
        postgresql_where=sa.text("status = 'RUNNING'")
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Drop partial index before reverting column type
    op.drop_index("uq_strategy_running_session", table_name="live_trading_sessions")
    
    op.alter_column(
        "live_trading_sessions",
        "status",
        existing_type=sa.Enum(*SESSION_STATE_VALUES, name="session_state"),
        type_=sa.String(length=32),
        postgresql_using="status::text",
        server_default="STARTING",
        existing_nullable=False,
    )
    
    # Recreate partial index
    op.create_index(
        "uq_strategy_running_session",
        "live_trading_sessions",
        ["strategy_id"],
        unique=True,
        postgresql_where=sa.text("status = 'RUNNING'")
    )
    sa.Enum(name="session_state").drop(op.get_bind(), checkfirst=True)
