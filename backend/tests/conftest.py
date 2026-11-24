"""Fixtures de banco para os testes que precisam do Postgres (T14, D35).

Os testes usam bancos próprios (``<banco>_test`` e ``<banco>_migration_test``), criados e
apagados aqui, derivados de ``DATABASE_URL`` (ou de ``TEST_DATABASE_URL``, se definida).
Sem Postgres no ar, esses testes são pulados com a instrução ``make db``.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import URL, create_engine, make_url, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.config import Settings

BACKEND_DIR = Path(__file__).resolve().parents[1]
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"


def _base_url() -> URL:
    explicit = os.environ.get("TEST_DATABASE_URL")
    if explicit:
        return make_url(explicit)
    url = make_url(Settings.load().database_url)
    return url.set(database=f"{url.database}_test")


def _admin_engine(url: URL) -> Engine:
    return create_engine(
        url.set(database="postgres"),
        isolation_level="AUTOCOMMIT",
        connect_args={"connect_timeout": 3},
    )


def _recreate_database(url: URL) -> None:
    admin = _admin_engine(url)
    try:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{url.database}" WITH (FORCE)'))
            conn.execute(text(f'CREATE DATABASE "{url.database}"'))
    except OperationalError as exc:
        pytest.skip(f"Postgres indisponível ({exc.orig}); rode `make db`.")
    finally:
        admin.dispose()


def _drop_database(url: URL) -> None:
    admin = _admin_engine(url)
    try:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{url.database}" WITH (FORCE)'))
    finally:
        admin.dispose()


def alembic_config(url: URL) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", url.render_as_string(hide_password=False))
    return config


@pytest.fixture(scope="session")
def database_url() -> Iterator[URL]:
    """Banco de teste criado do zero e migrado até ``head`` com Alembic."""
    url = _base_url()
    _recreate_database(url)
    command.upgrade(alembic_config(url), "head")
    yield url
    _drop_database(url)


@pytest.fixture
def empty_database_url() -> Iterator[URL]:
    """Banco vazio, sem migração, para testar a migração do zero."""
    base = _base_url()
    name = (base.database or "harness_test").removesuffix("_test")
    url = base.set(database=f"{name}_migration_test")
    _recreate_database(url)
    yield url
    _drop_database(url)


@pytest.fixture(scope="session")
def engine(database_url: URL) -> Iterator[Engine]:
    eng = create_engine(database_url)
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    """Sessão dentro de uma transação desfeita no fim do teste (testes isolados)."""
    with engine.connect() as conn:
        transaction = conn.begin()
        db = Session(bind=conn, join_transaction_mode="create_savepoint")
        try:
            yield db
        finally:
            db.close()
            transaction.rollback()
