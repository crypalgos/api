"""add_strategy_and_backtest_models

Revision ID: 11d3f2b5037e
Revises: 0355d7913b1e
Create Date: 2026-05-28 01:00:03.797807

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "11d3f2b5037e"
down_revision: Union[str, Sequence[str], None] = "0355d7913b1e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create strategies and backtests tables."""
    op.create_table(
        "strategies",
        sa.Column("id", sa.String(length=150), nullable=False),
        sa.Column("user_id", sa.String(length=150), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column("canvas_json", sa.JSON(), nullable=False),
        sa.Column("compiled_code", sa.String(), nullable=False),
        sa.Column(
            "is_code_modified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_strategies_id"), "strategies", ["id"], unique=True)
    op.create_index(
        op.f("ix_strategies_user_id"), "strategies", ["user_id"], unique=False
    )

    op.create_table(
        "backtests",
        sa.Column("id", sa.String(length=150), nullable=False),
        sa.Column("strategy_id", sa.String(length=150), nullable=False),
        sa.Column("exchange", sa.String(length=50), nullable=False),
        sa.Column("symbol", sa.String(length=50), nullable=False),
        sa.Column("start_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "initial_capital",
            sa.Float(),
            nullable=False,
            server_default=sa.text("10000.0"),
        ),
        sa.Column(
            "leverage", sa.Integer(), nullable=False, server_default=sa.text("1")
        ),
        sa.Column("metrics_json", sa.JSON(), nullable=False),
        sa.Column("charting_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["strategy_id"], ["strategies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_backtests_id"), "backtests", ["id"], unique=True)
    op.create_index(
        op.f("ix_backtests_strategy_id"), "backtests", ["strategy_id"], unique=False
    )


def downgrade() -> None:
    """Drop strategies and backtests tables."""
    op.drop_index(op.f("ix_backtests_strategy_id"), table_name="backtests")
    op.drop_index(op.f("ix_backtests_id"), table_name="backtests")
    op.drop_table("backtests")

    op.drop_index(op.f("ix_strategies_user_id"), table_name="strategies")
    op.drop_index(op.f("ix_strategies_id"), table_name="strategies")
    op.drop_table("strategies")
