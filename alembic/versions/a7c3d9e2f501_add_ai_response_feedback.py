"""add AI response evaluation feedback

Revision ID: a7c3d9e2f501
Revises: f1c8b3e6a492
Create Date: 2026-11-24
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a7c3d9e2f501"
down_revision: Union[str, Sequence[str], None] = "f1c8b3e6a492"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("ai_conversation_messages") as batch_op:
        batch_op.add_column(sa.Column("model_id", sa.String(length=36), nullable=True))
        batch_op.create_foreign_key(
            "fk_ai_conversation_messages_model_id_ai_models",
            "ai_models",
            ["model_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            op.f("ix_ai_conversation_messages_model_id"),
            ["model_id"],
            unique=False,
        )
    op.create_table(
        "ai_response_feedback",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("message_id", sa.String(length=36), nullable=False),
        sa.Column("model_id", sa.String(length=36), nullable=True),
        sa.Column("submitted_by", sa.String(length=128), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "rating >= 1 AND rating <= 5",
            name="ck_ai_response_feedback_rating",
        ),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["ai_conversation_messages.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["model_id"],
            ["ai_models.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "message_id",
            "submitted_by",
            name="uq_ai_response_feedback_actor_message",
        ),
    )
    op.create_index(
        op.f("ix_ai_response_feedback_message_id"),
        "ai_response_feedback",
        ["message_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ai_response_feedback_model_id"),
        "ai_response_feedback",
        ["model_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ai_response_feedback_tenant_id"),
        "ai_response_feedback",
        ["tenant_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_ai_response_feedback_tenant_id"),
        table_name="ai_response_feedback",
    )
    op.drop_index(
        op.f("ix_ai_response_feedback_model_id"),
        table_name="ai_response_feedback",
    )
    op.drop_index(
        op.f("ix_ai_response_feedback_message_id"),
        table_name="ai_response_feedback",
    )
    op.drop_table("ai_response_feedback")
    with op.batch_alter_table("ai_conversation_messages") as batch_op:
        batch_op.drop_index(op.f("ix_ai_conversation_messages_model_id"))
        batch_op.drop_constraint(
            "fk_ai_conversation_messages_model_id_ai_models",
            type_="foreignkey",
        )
        batch_op.drop_column("model_id")
