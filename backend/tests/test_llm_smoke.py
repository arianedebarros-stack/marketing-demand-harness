"""Rodada manual (make llm-smoke) testada com o SDK simulado: nunca chama a API real."""

from typing import Any

import anthropic
import httpx2
import pytest

from app.cli import llm_smoke
from app.core.config import ConfigError, Settings
from app.llm.anthropic_client import AnthropicClient
from tests.test_anthropic_client import CASE_02_TOOL_INPUT, FakeSDK, _response, _tool_use


def _settings() -> Settings:
    return Settings.model_validate({"anthropic_api_key": "sk-ant-nao-imprimir"})


def _client(*responses: Any) -> AnthropicClient:
    return AnthropicClient(model="claude-opus-5-5", sdk=FakeSDK(*responses))


def test_prints_interpretation_and_guardrails(capsys: pytest.CaptureFixture[str]) -> None:
    tool_input = {
        **CASE_02_TOOL_INPUT,
        "extracted": {**CASE_02_TOOL_INPUT["extracted"], "price": "R$ 9,90"},
    }
    client = _client(_response(_tool_use(tool_input)))

    code = llm_smoke.run(llm_smoke.DEFAULT_MESSAGE, settings=_settings(), client=client)

    out = capsys.readouterr().out
    assert code == 0
    assert "Modelo: claude-opus-5-5 | esforço: medium" in out
    assert '"brand": "Construjá"' in out
    assert "guardrail_discard: price = 'R$ 9,90' (number_not_in_text)" in out
    assert "sk-ant-nao-imprimir" not in out


def test_no_guardrail_events(capsys: pytest.CaptureFixture[str]) -> None:
    clean = {**CASE_02_TOOL_INPUT, "extracted": {"brand": "Construjá"}}
    client = _client(_response(_tool_use(clean)))
    llm_smoke.run("Arte da Construjá", settings=_settings(), client=client)
    assert "nenhum descarte ou ajuste" in capsys.readouterr().out


def _status_error(cls: type[anthropic.APIStatusError], status: int) -> anthropic.APIStatusError:
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls("erro", response=httpx2.Response(status, request=request), body=None)


def test_authentication_error_is_explained(capsys: pytest.CaptureFixture[str]) -> None:
    client = _client(_status_error(anthropic.AuthenticationError, 401))

    assert llm_smoke.run("Oi", settings=_settings(), client=client) == 1
    assert "Confira ANTHROPIC_API_KEY" in capsys.readouterr().out


def test_other_errors_return_1(capsys: pytest.CaptureFixture[str]) -> None:
    client = _client(_status_error(anthropic.InternalServerError, 529))

    assert llm_smoke.run("Oi", settings=_settings(), client=client) == 1
    assert "InternalServerError" in capsys.readouterr().out


def test_main_uses_default_message(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake_run(message: str, *, settings: Settings, client: Any = None) -> int:
        seen["message"] = message
        return 0

    monkeypatch.setattr(llm_smoke, "run", fake_run)

    assert llm_smoke.main([]) == 0
    assert seen["message"] == llm_smoke.DEFAULT_MESSAGE
    assert llm_smoke.main(["Faz", "um", "vídeo"]) == 0
    assert seen["message"] == "Faz um vídeo"


def test_main_reports_config_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def broken() -> Settings:
        raise ConfigError(".env: configuração inválida")

    monkeypatch.setattr(Settings, "load", staticmethod(broken))

    assert llm_smoke.main([]) == 1
    assert "configuração inválida" in capsys.readouterr().out
