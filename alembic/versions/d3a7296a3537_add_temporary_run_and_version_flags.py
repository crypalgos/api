"""add_temporary_run_and_version_flags

Revision ID: d3a7296a3537
Revises: 8a50093d76eb
Create Date: 2026-07-15 16:41:38.301642

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd3a7296a3537'
down_revision: Union[str, Sequence[str], None] = '8a50093d76eb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "research_runs",
        sa.Column("is_temporary", sa.Boolean(), server_default="false", nullable=False),
    )
    op.create_index(
        "idx_runs_strat_temp", "research_runs", ["strategy_id", "is_temporary"], unique=False
    )
    op.add_column(
        "strategy_versions",
        sa.Column("is_temporary", sa.Boolean(), server_default="false", nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("strategy_versions", "is_temporary")
    op.drop_index("idx_runs_strat_temp", table_name="research_runs")
    op.drop_column("research_runs", "is_temporary")
