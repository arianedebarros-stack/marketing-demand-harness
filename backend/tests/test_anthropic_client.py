"""T16 — AnthropicClient com o SDK simulado: nenhum teste chama a API real (D17, D37)."""

from __future__ import annotations

import json
from datetime import date, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch
from zoneinfo import ZoneInfo

import anthropic
import httpx2
import pytest
from pydantic import SecretStr

from app.core.config import Settings, load_app_config
from app.llm.anthropic_client import (
    TOOL_NAME,
    AnthropicClient,
    LLMRefusalError,
    LLMResponseError,
    strict_input_schema,
)
from app.llm.base import InterpretationContext
from app.llm.factory import build_llm_client
from app.llm.fake_client import FakeLLMClient
from app.llm.fallback import FallbackLLMClient, LLMUnavailableError
from app.llm.prompts import SYSTEM_PROMPT, build_user_prompt
from app.schemas.demand import Demand, RequestStatus
from app.services.pipeline import process_message

CONFIG = load_app_config()
TODAY = date(2026, 10, 19)  # segunda-feira
CASE_02 = (
    "Preciso de um feed 1080x1350 da Construjá para divulgar a promoção Krona amanhã. "
    "Os produtos e preços estão na planilha anexada e a promoção vale até sexta."
)
CASE_02_TOOL_INPUT: dict[str, Any] = {
    "classification": {"type": "Arte", "confidence": 0.96},
    "extracted": {
        "brand": "Construjá",
        "supplier": "Krona",
        "format": "Feed",
        "dimensions": "1080x1350",
        "objective": "Divulgar a promoção Krona",
        "product": "Conforme planilha anexada",
        "price": "Conforme planilha anexada",
        "deadline": "2026-10-20",
        "validity": "2026-10-23",
    },
    "is_promotional": True,
    "published_error": None,
    "dependencies": [],
    "files": ["Planilha de produtos e preços"],
}


def _context(
    messages: list[str] | None = None,
    known: dict[str, Any] | None = None,
    asked: list[str] | None = None,
) -> InterpretationContext:
    return InterpretationContext.build(
        CONFIG,
        today=TODAY,
        messages=messages or [CASE_02],
        known_fields=known or {},
        asked_fields=asked or [],
    )


def _tool_use(payload: dict[str, Any], name: str = TOOL_NAME) -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", id="toolu_1", name=name, input=payload)


def _response(*content: Any, stop_reason: str = "tool_use", **extra: Any) -> SimpleNamespace:
    return SimpleNamespace(
        content=list(content), stop_reason=stop_reason, stop_details=None, model="x", **extra
    )


class FakeSDK:
    """Imita ``anthropic.Anthropic`` só no que o cliente usa: ``beta.messages.create``."""

    def __init__(self, *responses: Any) -> None:
        self.calls: list[dict[str, Any]] = []
        self._responses = list(responses)
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        result = self._responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def _client(*responses: Any, **kwargs: Any) -> tuple[AnthropicClient, FakeSDK]:
    sdk = FakeSDK(*responses)
    return AnthropicClient(model="claude-opus-5-5", sdk=sdk, **kwargs), sdk


# --- Requisição ----------------------------------------------------------------------------


def test_request_uses_register_interpretation_tool() -> None:
    client, sdk = _client(_response(_tool_use(CASE_02_TOOL_INPUT)))

    client.interpret(_context())

    [call] = sdk.calls
    assert call["model"] == "claude-opus-5-5"
    [tool] = call["tools"]
    assert tool["name"] == TOOL_NAME == "register_interpretation"
    assert tool["strict"] is True
    assert tool["input_schema"] == strict_input_schema()
    # Opus 5.5 recusa tool_choice forçado (any/tool): auto + instrução no prompt (D37).
    assert call["tool_choice"] == {"type": "auto"}
    assert call["output_config"] == {"effort": "medium"}
    assert call["betas"] == ["server-side-fallback-2026-07-01"]
    assert call["fallbacks"] == "default"
    assert call["max_tokens"] == 16000
    assert call["system"] == SYSTEM_PROMPT
    assert "thinking" not in call  # Opus 5.5: pensamento adaptativo sempre ligado
    assert not {"temperature", "top_p", "top_k"} & set(call)
    assert call["messages"] == [{"role": "user", "content": build_user_prompt(_context())}]


def test_effort_and_max_tokens_are_configurable() -> None:
    client, sdk = _client(_response(_tool_use(CASE_02_TOOL_INPUT)), effort="low", max_tokens=8000)

    client.interpret(_context())

    assert sdk.calls[0]["output_config"] == {"effort": "low"}
    assert sdk.calls[0]["max_tokens"] == 8000


def test_strict_schema_is_accepted_by_structured_outputs() -> None:
    """Strict: todo objeto com additionalProperties false e todas as chaves em required;
    nada de $ref, default, minLength/maxLength/minimum/maximum (§8.1, D25, D37)."""
    schema = strict_input_schema()
    text = json.dumps(schema)

    for keyword in ("$ref", "$defs", '"default"', "minLength", "maxLength", "minimum", "maximum"):
        assert keyword not in text

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node["additionalProperties"] is False
                assert sorted(node["required"]) == sorted(node["properties"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(schema)
    extracted = schema["properties"]["extracted"]["properties"]
    assert extracted["brand"]["anyOf"] == [{"type": "string"}, {"type": "null"}]
    assert schema["properties"]["published_error"]["anyOf"] == [
        {"type": "boolean"},
        {"type": "null"},
    ]


# --- Prompt (§8.1) -------------------------------------------------------------------------


def test_system_prompt_has_the_spec_rules_and_no_business_values() -> None:
    for rule in (
        "nunca invente",
        "urgente",
        "vigência",
        "supplier",
        "dependências explícitas",
        "YYYY-MM-DD",
        TOOL_NAME,
    ):
        assert rule.lower() in SYSTEM_PROMPT.lower(), rule
    # Marcas, fornecedores e tipos vêm do contexto (config/), nunca fixos no prompt.
    for value in ("Construjá", "Ferjá", "Krona", "Gestor de Marketing"):
        assert value not in SYSTEM_PROMPT


def test_user_prompt_carries_the_context() -> None:
    context = _context(
        messages=["Faz uma arte da Krona.", "Construjá"],
        known={"supplier": "Krona", "deadline": "2026-10-20"},
        asked=["brand", "objective"],
    )

    prompt = build_user_prompt(context)

    assert "2026-10-19" in prompt and "segunda-feira" in prompt
    for name in ("Arte", "Vídeo", "Outro", "Construjá", "Ferjá", "Krona", "Tigre"):
        assert name in prompt
    assert '"deadline": "2026-10-20"' in prompt
    assert "brand, objective" in prompt
    assert "1. Faz uma arte da Krona." in prompt and "2. Construjá" in prompt
    assert "<mensagens_do_solicitante>" in prompt


def test_user_prompt_marks_empty_sections() -> None:
    prompt = build_user_prompt(_context())
    assert "Dados já registrados: nenhum" in prompt
    assert "Campos perguntados por último: nenhum" in prompt


# --- Resposta ------------------------------------------------------------------------------


def test_tool_input_becomes_interpretation() -> None:
    text = SimpleNamespace(type="text", text="Registrando.")
    thinking = SimpleNamespace(type="thinking", thinking="")
    client, _ = _client(_response(thinking, text, _tool_use(CASE_02_TOOL_INPUT)))

    interpretation = client.interpret(_context())

    assert interpretation.classification.type == "Arte"
    assert interpretation.extracted.provided()["brand"] == "Construjá"
    assert "company" not in interpretation.extracted.provided()  # null = ausente
    assert interpretation.published_error is None
    assert interpretation.files == ["Planilha de produtos e preços"]


def test_missing_tool_call_is_retried_once() -> None:
    """tool_choice auto não garante a chamada: uma nova tentativa, depois erro (D37)."""
    no_call = _response(SimpleNamespace(type="text", text="Olá"), stop_reason="end_turn")
    client, sdk = _client(no_call, _response(_tool_use(CASE_02_TOOL_INPUT)))

    assert client.interpret(_context()).classification.type == "Arte"
    assert len(sdk.calls) == 2


def test_missing_tool_call_twice_raises() -> None:
    no_call = _response(SimpleNamespace(type="text", text="Olá"), stop_reason="end_turn")
    client, sdk = _client(no_call, no_call)

    with pytest.raises(LLMResponseError, match="register_interpretation"):
        client.interpret(_context())
    assert len(sdk.calls) == 2


def test_other_tool_name_is_ignored() -> None:
    client, _ = _client(
        _response(_tool_use({}, name="outra")), _response(_tool_use({}, name="outra"))
    )
    with pytest.raises(LLMResponseError):
        client.interpret(_context())


def test_refusal_raises_with_category() -> None:
    refusal = _response(stop_reason="refusal")
    refusal.stop_details = SimpleNamespace(category="cyber", explanation="x")
    client, sdk = _client(refusal)

    with pytest.raises(LLMRefusalError, match="cyber"):
        client.interpret(_context())
    assert len(sdk.calls) == 1


def test_truncated_response_raises() -> None:
    client, _ = _client(_response(_tool_use({"classification": {}}), stop_reason="max_tokens"))
    with pytest.raises(LLMResponseError, match="max_tokens"):
        client.interpret(_context())


def test_input_outside_schema_raises() -> None:
    client, _ = _client(_response(_tool_use({"classification": {"type": "Arte"}})))
    with pytest.raises(LLMResponseError, match="schema"):
        client.interpret(_context())


# --- Falhas da API e fallback --------------------------------------------------------------


def _api_error() -> anthropic.APIStatusError:
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx2.Response(529, request=request, json={"error": {"message": "overloaded"}})
    return anthropic.InternalServerError("overloaded", response=response, body=None)


def test_api_error_falls_back_to_fake() -> None:
    client, _ = _client(_api_error())
    wrapped = FallbackLLMClient(client, FakeLLMClient())

    interpretation = wrapped.interpret(_context())

    assert wrapped.provider == "fake"
    assert wrapped.last_fallback is not None
    assert wrapped.last_fallback["failed"] == "anthropic"
    assert interpretation.classification.type == "Arte"


def test_api_error_without_fallback_is_unavailable() -> None:
    client, _ = _client(_api_error())
    with pytest.raises(LLMUnavailableError):
        FallbackLLMClient(client, None).interpret(_context())


# --- Factory e settings (D17) --------------------------------------------------------------


def _settings(**values: Any) -> Settings:
    return Settings.model_validate({"anthropic_api_key": None, **values})


def test_default_model_is_from_d17() -> None:
    assert Settings.model_fields["llm_model"].default == "claude-opus-5-5"
    assert Settings.model_fields["llm_effort"].default == "medium"


def test_factory_builds_anthropic_client_with_settings() -> None:
    settings = _settings(
        llm_provider="anthropic",
        llm_fallback=True,
        llm_model="claude-sonnet-5-5",
        llm_effort="low",
        llm_timeout_seconds=30,
        anthropic_api_key="sk-ant-teste",
    )
    with patch("app.llm.anthropic_client.anthropic.Anthropic") as sdk_class:
        client = build_llm_client(settings)

    assert isinstance(client, FallbackLLMClient)
    primary = client.primary
    assert isinstance(primary, AnthropicClient)
    assert (primary.model, primary.effort) == ("claude-sonnet-5-5", "low")
    sdk_class.assert_called_once_with(api_key="sk-ant-teste", timeout=30.0)


def test_factory_without_key_lets_sdk_resolve_credentials() -> None:
    with patch("app.llm.anthropic_client.anthropic.Anthropic") as sdk_class:
        build_llm_client(_settings(llm_provider="anthropic"))
    sdk_class.assert_called_once_with(timeout=60.0)


def test_from_settings_accepts_secret() -> None:
    with patch("app.llm.anthropic_client.anthropic.Anthropic") as sdk_class:
        AnthropicClient.from_settings(_settings(anthropic_api_key=SecretStr("sk-ant-x")))
    assert sdk_class.call_args.kwargs["api_key"] == "sk-ant-x"


@pytest.mark.parametrize("effort", ["baixo", "ultra"])
def test_invalid_effort_is_rejected(effort: str) -> None:
    with pytest.raises(ValueError):
        _settings(llm_effort=effort)


# --- Ponta a ponta com o pipeline ----------------------------------------------------------


def test_pipeline_with_mocked_anthropic_reaches_ready_for_triage() -> None:
    """Com o SDK simulado, a interpretação passa pelos guardrails e regras até 100%."""
    client, _ = _client(_response(_tool_use(CASE_02_TOOL_INPUT)))
    now = datetime(2026, 10, 19, 9, 0, tzinfo=ZoneInfo("America/Sao_Paulo"))

    result = process_message(
        Demand(requester="Ana", department="Comercial"),
        [CASE_02],
        llm=client,
        config=CONFIG,
        now=now,
        tz=ZoneInfo("America/Sao_Paulo"),
    )

    demand = result.demand
    assert demand.status is RequestStatus.READY_FOR_TRIAGE
    assert (demand.brand, demand.channel, demand.dimensions) == (
        "Construjá",
        "Instagram",
        "1080 × 1350 px",
    )
    interpretation = next(e for e in result.events if e.action == "interpretation")
    assert interpretation.new_value["provider"] == "anthropic"
