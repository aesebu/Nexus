"""add AI agent registry

Revision ID: a14c7f93d052
Revises: 6e5f9f0a2b1c
Create Date: 2026-11-23
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a14c7f93d052"
down_revision: Union[str, Sequence[str], None] = "6e5f9f0a2b1c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ai_agents",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("agent_type", sa.String(length=64), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("instructions", sa.Text(), nullable=False),
        sa.Column("capabilities", sa.JSON(), nullable=False),
        sa.Column("tools", sa.JSON(), nullable=False),
        sa.Column("preferred_provider", sa.String(length=128), nullable=True),
        sa.Column(
            "status",
            sa.Enum("REGISTERED", "ENABLED", "DISABLED", name="agentstatus"),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_ai_agent_tenant_name"),
    )
    op.create_index(
        op.f("ix_ai_agents_agent_type"),
        "ai_agents",
        ["agent_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ai_agents_status"),
        "ai_agents",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ai_agents_tenant_id"),
        "ai_agents",
        ["tenant_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_ai_agents_tenant_id"), table_name="ai_agents")
    op.drop_index(op.f("ix_ai_agents_status"), table_name="ai_agents")
    op.drop_index(op.f("ix_ai_agents_agent_type"), table_name="ai_agents")
    op.drop_table("ai_agents")
