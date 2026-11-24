"""add outbound webhook integrations

Revision ID: f1c8b3e6a492
Revises: e6f4a8d1c920
Create Date: 2026-11-24
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f1c8b3e6a492"
down_revision: Union[str, Sequence[str], None] = "e6f4a8d1c920"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "integration_webhooks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("target_url", sa.String(length=2048), nullable=False),
        sa.Column("secret_name", sa.String(length=128), nullable=False),
        sa.Column("event_types", sa.JSON(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "REGISTERED",
                "ENABLED",
                "DISABLED",
                name="integrationwebhookstatus",
            ),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "name",
            name="uq_integration_webhook_tenant_name",
        ),
    )
    op.create_index(
        op.f("ix_integration_webhooks_status"),
        "integration_webhooks",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_integration_webhooks_tenant_id"),
        "integration_webhooks",
        ["tenant_id"],
        unique=False,
    )

    op.create_table(
        "integration_webhook_deliveries",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("webhook_id", sa.String(length=36), nullable=False),
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["control_events.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["control_tasks.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["webhook_id"],
            ["integration_webhooks.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "webhook_id",
            "event_id",
            name="uq_integration_webhook_delivery_event",
        ),
    )
    op.create_index(
        op.f("ix_integration_webhook_deliveries_event_id"),
        "integration_webhook_deliveries",
        ["event_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_integration_webhook_deliveries_tenant_id"),
        "integration_webhook_deliveries",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_integration_webhook_deliveries_webhook_id"),
        "integration_webhook_deliveries",
        ["webhook_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_integration_webhook_deliveries_task_id"),
        "integration_webhook_deliveries",
        ["task_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_integration_webhook_deliveries_task_id"),
        table_name="integration_webhook_deliveries",
    )
    op.drop_index(
        op.f("ix_integration_webhook_deliveries_webhook_id"),
        table_name="integration_webhook_deliveries",
    )
    op.drop_index(
        op.f("ix_integration_webhook_deliveries_tenant_id"),
        table_name="integration_webhook_deliveries",
    )
    op.drop_index(
        op.f("ix_integration_webhook_deliveries_event_id"),
        table_name="integration_webhook_deliveries",
    )
    op.drop_table("integration_webhook_deliveries")
    op.drop_index(
        op.f("ix_integration_webhooks_tenant_id"),
        table_name="integration_webhooks",
    )
    op.drop_index(
        op.f("ix_integration_webhooks_status"),
        table_name="integration_webhooks",
    )
    op.drop_table("integration_webhooks")
