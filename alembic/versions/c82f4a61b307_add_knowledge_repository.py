"""add tenant-scoped knowledge repository

Revision ID: c82f4a61b307
Revises: a14c7f93d052
Create Date: 2026-11-23
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c82f4a61b307"
down_revision: Union[str, Sequence[str], None] = "a14c7f93d052"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "knowledge_documents",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("source", sa.String(length=500), nullable=False),
        sa.Column(
            "status",
            sa.Enum("DRAFT", "ACTIVE", "INACTIVE", name="knowledgedocumentstatus"),
            nullable=False,
        ),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "name",
            name="uq_knowledge_document_tenant_name",
        ),
    )
    op.create_index(
        op.f("ix_knowledge_documents_status"),
        "knowledge_documents",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_documents_tenant_id"),
        "knowledge_documents",
        ["tenant_id"],
        unique=False,
    )
    op.create_table(
        "knowledge_document_versions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["knowledge_documents.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_id",
            "version",
            name="uq_knowledge_document_version",
        ),
    )
    op.create_index(
        op.f("ix_knowledge_document_versions_document_id"),
        "knowledge_document_versions",
        ["document_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_document_versions_tenant_id"),
        "knowledge_document_versions",
        ["tenant_id"],
        unique=False,
    )
    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("document_version_id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("start_offset", sa.Integer(), nullable=False),
        sa.Column("end_offset", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["knowledge_documents.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id"],
            ["knowledge_document_versions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_version_id",
            "chunk_index",
            name="uq_knowledge_chunk_version_index",
        ),
    )
    op.create_index(
        op.f("ix_knowledge_chunks_document_id"),
        "knowledge_chunks",
        ["document_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_chunks_document_version_id"),
        "knowledge_chunks",
        ["document_version_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_chunks_tenant_id"),
        "knowledge_chunks",
        ["tenant_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_knowledge_chunks_tenant_id"), table_name="knowledge_chunks")
    op.drop_index(
        op.f("ix_knowledge_chunks_document_version_id"),
        table_name="knowledge_chunks",
    )
    op.drop_index(
        op.f("ix_knowledge_chunks_document_id"),
        table_name="knowledge_chunks",
    )
    op.drop_table("knowledge_chunks")
    op.drop_index(
        op.f("ix_knowledge_document_versions_tenant_id"),
        table_name="knowledge_document_versions",
    )
    op.drop_index(
        op.f("ix_knowledge_document_versions_document_id"),
        table_name="knowledge_document_versions",
    )
    op.drop_table("knowledge_document_versions")
    op.drop_index(
        op.f("ix_knowledge_documents_tenant_id"),
        table_name="knowledge_documents",
    )
    op.drop_index(
        op.f("ix_knowledge_documents_status"),
        table_name="knowledge_documents",
    )
    op.drop_table("knowledge_documents")
