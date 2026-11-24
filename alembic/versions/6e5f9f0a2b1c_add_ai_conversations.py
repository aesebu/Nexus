"""add AI conversations

Revision ID: 6e5f9f0a2b1c
Revises: 11d94d75e9a2
Create Date: 2026-11-23
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "6e5f9f0a2b1c"
down_revision: Union[str, Sequence[str], None] = "11d94d75e9a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ai_conversations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_ai_conversations_created_by"),
        "ai_conversations",
        ["created_by"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ai_conversations_tenant_id"),
        "ai_conversations",
        ["tenant_id"],
        unique=False,
    )
    op.create_table(
        "ai_conversation_messages",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("conversation_id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["ai_conversations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "conversation_id",
            "sequence",
            name="uq_ai_conversation_message_sequence",
        ),
    )
    op.create_index(
        op.f("ix_ai_conversation_messages_conversation_id"),
        "ai_conversation_messages",
        ["conversation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ai_conversation_messages_tenant_id"),
        "ai_conversation_messages",
        ["tenant_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_ai_conversation_messages_tenant_id"),
        table_name="ai_conversation_messages",
    )
    op.drop_index(
        op.f("ix_ai_conversation_messages_conversation_id"),
        table_name="ai_conversation_messages",
    )
    op.drop_table("ai_conversation_messages")
    op.drop_index(
        op.f("ix_ai_conversations_tenant_id"),
        table_name="ai_conversations",
    )
    op.drop_index(
        op.f("ix_ai_conversations_created_by"),
        table_name="ai_conversations",
    )
    op.drop_table("ai_conversations")
