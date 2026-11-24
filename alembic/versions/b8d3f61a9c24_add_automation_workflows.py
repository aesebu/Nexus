"""add automation workflows and runs

Revision ID: b8d3f61a9c24
Revises: 4f7c2d9a1e63
Create Date: 2026-11-23
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b8d3f61a9c24"
down_revision: Union[str, Sequence[str], None] = "4f7c2d9a1e63"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "automation_workflows",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("steps", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("DRAFT", "ACTIVE", "INACTIVE", name="automationworkflowstatus"),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "name",
            name="uq_automation_workflow_tenant_name",
        ),
    )
    op.create_index(
        op.f("ix_automation_workflows_status"),
        "automation_workflows",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_automation_workflows_tenant_id"),
        "automation_workflows",
        ["tenant_id"],
        unique=False,
    )

    op.create_table(
        "automation_workflow_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("workflow_id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("workflow_version", sa.Integer(), nullable=False),
        sa.Column("input", sa.JSON(), nullable=False),
        sa.Column("steps_snapshot", sa.JSON(), nullable=False),
        sa.Column("step_results", sa.JSON(), nullable=False),
        sa.Column("result_snapshot", sa.JSON(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "QUEUED",
                "IN_PROGRESS",
                "COMPLETED",
                "FAILED",
                "CANCELLED",
                name="automationworkflowrunstatus",
            ),
            nullable=False,
        ),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["control_tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workflow_id"],
            ["automation_workflows.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_automation_workflow_runs_status"),
        "automation_workflow_runs",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_automation_workflow_runs_tenant_id"),
        "automation_workflow_runs",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_automation_workflow_runs_workflow_id"),
        "automation_workflow_runs",
        ["workflow_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_automation_workflow_runs_task_id"),
        "automation_workflow_runs",
        ["task_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_automation_workflow_runs_task_id"),
        table_name="automation_workflow_runs",
    )
    op.drop_index(
        op.f("ix_automation_workflow_runs_workflow_id"),
        table_name="automation_workflow_runs",
    )
    op.drop_index(
        op.f("ix_automation_workflow_runs_tenant_id"),
        table_name="automation_workflow_runs",
    )
    op.drop_index(
        op.f("ix_automation_workflow_runs_status"),
        table_name="automation_workflow_runs",
    )
    op.drop_table("automation_workflow_runs")
    op.drop_index(
        op.f("ix_automation_workflows_tenant_id"),
        table_name="automation_workflows",
    )
    op.drop_index(
        op.f("ix_automation_workflows_status"),
        table_name="automation_workflows",
    )
    op.drop_table("automation_workflows")
