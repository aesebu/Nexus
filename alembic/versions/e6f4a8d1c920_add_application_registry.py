"""add tenant-scoped application registry

Revision ID: e6f4a8d1c920
Revises: d7a1c8e4f502
Create Date: 2026-11-24
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e6f4a8d1c920"
down_revision: Union[str, Sequence[str], None] = "d7a1c8e4f502"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "application_registry",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("app_key", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column(
            "status",
            sa.Enum("REGISTERED", "ENABLED", "DISABLED", name="applicationstatus"),
            nullable=False,
        ),
        sa.Column("permission_scopes", sa.JSON(), nullable=False),
        sa.Column("data_scopes", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "app_key",
            name="uq_application_registry_tenant_key",
        ),
    )
    op.create_index(
        op.f("ix_application_registry_status"),
        "application_registry",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_application_registry_tenant_id"),
        "application_registry",
        ["tenant_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_application_registry_tenant_id"),
        table_name="application_registry",
    )
    op.drop_index(
        op.f("ix_application_registry_status"),
        table_name="application_registry",
    )
    op.drop_table("application_registry")
