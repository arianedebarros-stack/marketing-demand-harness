"""Dependências da API (sobrescritas nos testes: sessão, "agora" e LLM)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.core.config import AppConfig, Settings, get_app_config, get_settings
from app.core.db import session_scope
from app.integrations.asana import AsanaTaskManager
from app.integrations.base import TaskManagerConnector
from app.integrations.local import LocalTaskManager
from app.llm.base import LLMClient
from app.llm.factory import build_llm_client


def get_session() -> Iterator[Session]:
    yield from session_scope()


def get_config() -> AppConfig:
    return get_app_config()


def get_tz() -> ZoneInfo:
    return get_settings().timezone


def get_now() -> datetime:
    return datetime.now(get_tz())


def get_llm() -> LLMClient:
    return build_llm_client(get_settings())


def build_task_manager(settings: Settings) -> TaskManagerConnector:
    """Sistema de tarefas pela setting ``TASK_MANAGER`` (§11, D38); o padrão é ``local``."""
    if settings.task_manager == "asana":
        return AsanaTaskManager.from_settings(settings)
    return LocalTaskManager()


def get_task_manager() -> TaskManagerConnector:
    return build_task_manager(get_settings())
