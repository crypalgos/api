"""Track uploaded S3 keys for a live session's finalized workspace archive.

Revision ID: acb0b5b8545f
Revises: d4e5f6a7b8c9
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'acb0b5b8545f'
down_revision: Union[str, Sequence[str], None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """{candles, strategy_events, session_metadata: s3_key}, populated once
    SessionWorkspaceArchive.close() has confirmed the upload — mirrors
    ResearchRun.artifact_manifest. NULL means the workspace is either still
    running or its local files haven't been archived yet (crash/pending retry)."""
    op.add_column(
        "live_trading_sessions",
        sa.Column("artifact_manifest", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("live_trading_sessions", "artifact_manifest")
