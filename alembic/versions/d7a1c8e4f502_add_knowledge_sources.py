"""add tenant-scoped knowledge source registry

Revision ID: d7a1c8e4f502
Revises: b8d3f61a9c24
Create Date: 2026-11-23
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d7a1c8e4f502"
down_revision: Union[str, Sequence[str], None] = "b8d3f61a9c24"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "knowledge_sources",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=True),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("knowledge_domains", sa.JSON(), nullable=False),
        sa.Column(
            "credibility",
            sa.Enum("S1", "S2", "S3", "S4", "S5", name="knowledgesourcecredibility"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "DISCOVERED",
                "VERIFIED",
                "RESTRICTED",
                "DEPRECATED",
                name="knowledgesourcestatus",
            ),
            nullable=False,
        ),
        sa.Column("access_method", sa.String(length=64), nullable=False),
        sa.Column("license", sa.String(length=500), nullable=True),
        sa.Column("update_frequency", sa.String(length=64), nullable=True),
        sa.Column("security_risk", sa.String(length=500), nullable=False),
        sa.Column("research_status", sa.String(length=64), nullable=False),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "name",
            name="uq_knowledge_source_tenant_name",
        ),
    )
    op.create_index(
        op.f("ix_knowledge_sources_tenant_id"),
        "knowledge_sources",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_sources_credibility"),
        "knowledge_sources",
        ["credibility"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_sources_status"),
        "knowledge_sources",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_knowledge_sources_status"),
        table_name="knowledge_sources",
    )
    op.drop_index(
        op.f("ix_knowledge_sources_credibility"),
        table_name="knowledge_sources",
    )
    op.drop_index(
        op.f("ix_knowledge_sources_tenant_id"),
        table_name="knowledge_sources",
    )
    op.drop_table("knowledge_sources")
