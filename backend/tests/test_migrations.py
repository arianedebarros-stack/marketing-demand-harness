"""T14 — a migração sobe do zero e bate com os models (SPEC §10)."""

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import URL, create_engine, inspect

from app.models import Base
from tests.conftest import alembic_config

TABLES = {"users", "requests", "messages", "tasks", "dependencies", "audit_log"}


def test_migration_runs_from_scratch_and_matches_models(empty_database_url: URL) -> None:
    config = alembic_config(empty_database_url)
    engine = create_engine(empty_database_url)
    try:
        command.upgrade(config, "head")

        with engine.connect() as conn:
            assert set(inspect(conn).get_table_names()) >= TABLES
            diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
        assert diff == []
    finally:
        engine.dispose()


def test_migration_downgrades_and_upgrades_again(empty_database_url: URL) -> None:
    config = alembic_config(empty_database_url)
    engine = create_engine(empty_database_url)
    try:
        command.upgrade(config, "head")
        command.downgrade(config, "base")
        with engine.connect() as conn:
            assert set(inspect(conn).get_table_names()) <= {"alembic_version"}

        command.upgrade(config, "head")
        with engine.connect() as conn:
            assert set(inspect(conn).get_table_names()) >= TABLES
    finally:
        engine.dispose()


def test_all_spec_columns_exist() -> None:
    """§10: colunas de cada tabela."""
    expected = {
        "requests": {
            "id", "requester", "department", "channel", "status", "demand",
            "created_at", "updated_at",
        },
        "messages": {"id", "request_id", "role", "text", "created_at"},
        "tasks": {
            "id", "request_id", "external_task_id", "title", "type", "brand", "supplier",
            "campaign", "assigned_to", "priority", "deadline", "blocked", "status", "briefing",
            "briefing_score", "created_at",
        },
        "dependencies": {"id", "task_id", "description", "owner", "status"},
        "audit_log": {
            "id", "request_id", "task_id", "actor", "action", "previous_value", "new_value",
            "timestamp",
        },
    }  # fmt: skip

    for table, columns in expected.items():
        assert columns <= set(Base.metadata.tables[table].columns.keys()), table
