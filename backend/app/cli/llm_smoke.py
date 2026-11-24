"""Rodada manual com o LLM real (T16): ``make llm-smoke`` ou ``make llm-smoke MSG="..."``.

Chama a API da Anthropic uma vez, sem fallback para o Fake, com a chave de ``ANTHROPIC_API_KEY``
(``.env``) e o modelo de ``LLM_MODEL``. Mostra a interpretação e o que os guardrails descartariam.
Nunca imprime a chave. Não roda nos testes automáticos (eles usam o SDK simulado).
"""

from __future__ import annotations

import json
import sys
from datetime import datetime

import anthropic

from app.core.config import ConfigError, Settings, load_app_config
from app.engines.guardrails import apply_guardrails
from app.llm.anthropic_client import AnthropicClient, LLMResponseError
from app.llm.base import InterpretationContext

DEFAULT_MESSAGE = (
    "Preciso de um feed 1080x1350 da Construjá para divulgar a promoção Krona amanhã. "
    "Os produtos e preços estão na planilha anexada e a promoção vale até sexta."
)


def run(message: str, *, settings: Settings, client: AnthropicClient | None = None) -> int:
    config = load_app_config(settings.config_dir)
    llm = client or AnthropicClient.from_settings(settings)
    today = datetime.now(settings.timezone).date()
    context = InterpretationContext.build(
        config, today=today, messages=[message], known_fields={}, asked_fields=[]
    )
    print(f"Modelo: {llm.model} | esforço: {llm.effort} | hoje: {today.isoformat()}")
    print(f"Mensagem: {message}\n")
    try:
        interpretation = llm.interpret(context)
    except anthropic.AuthenticationError:
        print("ERRO: a API recusou a credencial. Confira ANTHROPIC_API_KEY no .env.")
        return 1
    except (anthropic.APIError, LLMResponseError) as exc:
        print(f"ERRO: {type(exc).__name__}: {exc}")
        return 1

    print("Interpretação (validada pelo schema):")
    print(json.dumps(interpretation.model_dump(mode="json"), ensure_ascii=False, indent=2))
    guarded = apply_guardrails(
        interpretation, requester_text=message, config=config, field_origin={}
    )
    print("\nGuardrails:")
    if not guarded.events:
        print("  nenhum descarte ou ajuste")
    for event in guarded.events:
        payload = event.audit_payload()
        print(f"  {payload['action']}: {event.field} = {event.value!r} ({event.reason})")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    message = " ".join(args).strip() or DEFAULT_MESSAGE
    try:
        settings = Settings.load()
    except ConfigError as exc:
        print(f"ERRO de configuração:\n{exc}")
        return 1
    return run(message, settings=settings)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
