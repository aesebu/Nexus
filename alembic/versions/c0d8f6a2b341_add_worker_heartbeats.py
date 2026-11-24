"""add worker heartbeats

Revision ID: c0d8f6a2b341
Revises: a7c3d9e2f501
Create Date: 2026-11-24
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c0d8f6a2b341"
down_revision: Union[str, Sequence[str], None] = "a7c3d9e2f501"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "worker_heartbeats",
        sa.Column("worker_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('RUNNING', 'STOPPED')",
            name="ck_worker_heartbeat_status",
        ),
        sa.PrimaryKeyConstraint("worker_id"),
    )
    op.create_index(
        "ix_worker_heartbeats_status_last_seen_at",
        "worker_heartbeats",
        ["status", "last_seen_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_worker_heartbeats_status_last_seen_at",
        table_name="worker_heartbeats",
    )
    op.drop_table("worker_heartbeats")
