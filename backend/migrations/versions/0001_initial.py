"""Cria as tabelas iniciais (SPEC §10, T14).

Revision ID: 0001
Revises:
Create Date: 2026-11-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("requester", sa.String(length=200), nullable=False),
        sa.Column("department", sa.String(length=200), nullable=False),
        sa.Column("channel", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("demand", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('RECEIVED', 'PARSED', 'VALIDATING', 'NEEDS_INFORMATION', "
            "'READY_FOR_TRIAGE', 'TRIAGED', 'PENDING_APPROVAL', 'APPROVED', 'TASK_CREATED', "
            "'CANCELLED', 'REJECTED', 'ERROR')",
            name=op.f("ck_requests_status"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_requests")),
    )
    op.create_index(op.f("ix_requests_status"), "requests", ["status"], unique=False)
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("department", sa.String(length=200), nullable=True),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("role IN ('requester', 'manager')", name=op.f("ck_users_role")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
    )
    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("role IN ('requester', 'assistant')", name=op.f("ck_messages_role")),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["requests.id"],
            name=op.f("fk_messages_request_id_requests"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_messages")),
    )
    op.create_index(op.f("ix_messages_request_id"), "messages", ["request_id"], unique=False)
    op.create_table(
        "tasks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("external_task_id", sa.String(length=100), nullable=True),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("type", sa.String(length=50), nullable=False),
        sa.Column("brand", sa.String(length=100), nullable=True),
        sa.Column("supplier", sa.String(length=100), nullable=True),
        sa.Column("campaign", sa.String(length=200), nullable=True),
        sa.Column("assigned_to", sa.String(length=50), nullable=True),
        sa.Column("priority", sa.String(length=20), nullable=True),
        sa.Column("deadline", sa.Date(), nullable=True),
        sa.Column("blocked", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("status", sa.String(length=20), server_default="Aberta", nullable=False),
        sa.Column("briefing", sa.Text(), nullable=False),
        sa.Column("briefing_score", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "priority IS NULL OR priority IN ('Crítica', 'Alta', 'Normal', 'Baixa')",
            name=op.f("ck_tasks_priority"),
        ),
        sa.CheckConstraint("status IN ('Aberta', 'Concluída')", name=op.f("ck_tasks_status")),
        sa.ForeignKeyConstraint(
            ["request_id"], ["requests.id"], name=op.f("fk_tasks_request_id_requests")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tasks")),
        sa.UniqueConstraint("external_task_id", name=op.f("uq_tasks_external_task_id")),
    )
    op.create_index(op.f("ix_tasks_assigned_to"), "tasks", ["assigned_to"], unique=False)
    op.create_index(op.f("ix_tasks_request_id"), "tasks", ["request_id"], unique=False)
    op.create_index(op.f("ix_tasks_status"), "tasks", ["status"], unique=False)
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=True),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("actor", sa.String(length=20), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("previous_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("new_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "timestamp", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "actor IN ('llm', 'harness', 'user', 'manager')", name=op.f("ck_audit_log_actor")
        ),
        sa.ForeignKeyConstraint(
            ["request_id"], ["requests.id"], name=op.f("fk_audit_log_request_id_requests")
        ),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], name=op.f("fk_audit_log_task_id_tasks")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_log")),
    )
    op.create_index(op.f("ix_audit_log_action"), "audit_log", ["action"], unique=False)
    op.create_index(op.f("ix_audit_log_request_id"), "audit_log", ["request_id"], unique=False)
    op.create_index(op.f("ix_audit_log_task_id"), "audit_log", ["task_id"], unique=False)
    op.create_table(
        "dependencies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("owner", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="Pendente", nullable=False),
        sa.CheckConstraint(
            "status IN ('Pendente', 'Resolvida')", name=op.f("ck_dependencies_status")
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["tasks.id"],
            name=op.f("fk_dependencies_task_id_tasks"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dependencies")),
    )
    op.create_index(op.f("ix_dependencies_task_id"), "dependencies", ["task_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_dependencies_task_id"), table_name="dependencies")
    op.drop_table("dependencies")
    op.drop_index(op.f("ix_audit_log_task_id"), table_name="audit_log")
    op.drop_index(op.f("ix_audit_log_request_id"), table_name="audit_log")
    op.drop_index(op.f("ix_audit_log_action"), table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_index(op.f("ix_tasks_status"), table_name="tasks")
    op.drop_index(op.f("ix_tasks_request_id"), table_name="tasks")
    op.drop_index(op.f("ix_tasks_assigned_to"), table_name="tasks")
    op.drop_table("tasks")
    op.drop_index(op.f("ix_messages_request_id"), table_name="messages")
    op.drop_table("messages")
    op.drop_table("users")
    op.drop_index(op.f("ix_requests_status"), table_name="requests")
    op.drop_table("requests")
