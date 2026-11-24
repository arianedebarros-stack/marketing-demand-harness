"""Escolha do LLM pelas settings e fallback (§9, D36). Nunca chama o LLM real."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pytest

from app.api import deps
from app.core.config import Settings, load_app_config
from app.integrations.local import LocalTaskManager
from app.llm.base import InterpretationContext
from app.llm.factory import build_llm_client
from app.llm.fake_client import FakeLLMClient
from app.llm.fallback import FallbackLLMClient, LLMUnavailableError
from app.models import Task

CONTEXT = InterpretationContext.build(
    load_app_config(), today=date(2026, 10, 19), messages=["Faz uma arte"], known_fields={},
    asked_fields=[],
)  # fmt: skip


def _settings(**values: object) -> Settings:
    return Settings.model_validate({"anthropic_api_key": None, **values})


def test_fake_provider() -> None:
    assert isinstance(build_llm_client(_settings(llm_provider="fake")), FakeLLMClient)


class _FailingSDK:
    """SDK simulado que sempre falha (nunca chama a API real)."""

    def __init__(self, **options: object) -> None:
        self.beta = self

    @property
    def messages(self) -> _FailingSDK:
        return self

    def create(self, **kwargs: object) -> object:
        raise RuntimeError("sem rede nos testes")


@patch("app.llm.anthropic_client.anthropic.Anthropic", _FailingSDK)
def test_anthropic_failure_falls_back_to_fake() -> None:
    client = build_llm_client(_settings(llm_provider="anthropic", llm_fallback=True))

    assert isinstance(client, FallbackLLMClient)
    interpretation = client.interpret(CONTEXT)
    assert interpretation.classification.type == "Arte"
    assert client.provider == "fake"
    assert client.last_fallback is not None
    assert client.last_fallback["failed"] == "anthropic"


@patch("app.llm.anthropic_client.anthropic.Anthropic", _FailingSDK)
def test_anthropic_without_fallback_raises() -> None:
    client = build_llm_client(_settings(llm_provider="anthropic", llm_fallback=False))

    with pytest.raises(LLMUnavailableError):
        client.interpret(CONTEXT)


def test_fallback_not_used_when_primary_works() -> None:
    client = FallbackLLMClient(FakeLLMClient(), None)

    client.interpret(CONTEXT)

    assert client.provider == "fake"
    assert client.last_fallback is None


def test_local_task_manager_needs_saved_task() -> None:
    with pytest.raises(ValueError):
        LocalTaskManager().create_task(Task(title="X"))


def test_default_dependencies() -> None:
    assert deps.get_now().tzinfo is not None
    assert isinstance(deps.get_task_manager(), LocalTaskManager)
    assert deps.get_llm().provider in {"fake", "anthropic"}
    assert deps.get_config() is deps.get_config()
