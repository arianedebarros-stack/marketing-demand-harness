"""Pipeline da demanda: interpretação → guardrails → merge → regras → validação → estado.

SPEC §7, §8, §15; decisões D01, D06, D07, D27, D28, D31.

O LLM só interpreta. Tudo o que decide (merge, regras, score, estado) é código determinístico.
Este serviço não grava nada: devolve a nova demanda e os eventos de audit, que a camada de
persistência (T14/T15) grava em ``audit_log``. A triagem automática da D01 entra depois de
``READY_FOR_TRIAGE`` quando os engines da T11–T13 existirem.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from pydantic_core import to_jsonable_python

from app.core.config import AppConfig
from app.core.state_machine import InvalidTransition, can_transition, transition
from app.core.text import digit_groups, normalize
from app.engines.dependency import merge_dependencies
from app.engines.guardrails import apply_guardrails
from app.engines.rules import apply_rules
from app.engines.validator import validate_demand
from app.llm.base import InterpretationContext, LLMClient
from app.schemas.api import NextAction, Question, ScoreBand
from app.schemas.audit import AuditEvent
from app.schemas.demand import (
    EXTRACTABLE_FIELDS,
    Demand,
    FieldOrigin,
    RequestStatus,
    RequiredFile,
)
from app.schemas.llm import LLMInterpretation

S = RequestStatus
MANAGER = FieldOrigin.MANAGER
LLM = FieldOrigin.LLM
MESSAGE = FieldOrigin.MESSAGE


@dataclass(frozen=True)
class PipelineResult:
    demand: Demand
    questions: list[Question]
    # None em READY_FOR_TRIAGE: a triagem (T11–T13) define o próximo passo (D01, D31).
    next_action: NextAction | None
    score_band: ScoreBand
    events: list[AuditEvent]


def process_message(
    demand: Demand,
    messages: list[str],
    *,
    llm: LLMClient,
    config: AppConfig,
    now: datetime,
    tz: ZoneInfo,
) -> PipelineResult:
    """Processa a mensagem mais recente do solicitante.

    ``messages`` é o histórico completo das mensagens do solicitante, em ordem, já com a nova
    (§8.1). A demanda de entrada não é alterada.
    """
    current = demand.status
    first_step = S.PARSED if current is S.RECEIVED else S.VALIDATING
    if not can_transition(current, first_step):
        # Recusa antes de chamar o LLM; quem chama grava ``audit_payload()`` da exceção.
        raise InvalidTransition(current, first_step)

    events = [
        AuditEvent("user", "message_received", new_value={"text": messages[-1] if messages else ""})
    ]
    asked = (
        [f for q in validate_demand(demand, config=config).questions for f in q.fields]
        if current is S.NEEDS_INFORMATION
        else []
    )
    context = InterpretationContext.build(
        config,
        today=_local_date(now, tz),
        messages=messages,
        known_fields=_known_fields(demand),
        asked_fields=asked,
    )
    interpretation = llm.interpret(context)
    events.append(
        AuditEvent(
            "llm",
            "interpretation",
            new_value={
                "provider": llm.provider,
                "output": interpretation.model_dump(mode="json"),
            },
        )
    )

    requester_text = "\n".join(messages)
    guarded = apply_guardrails(
        interpretation,
        requester_text=requester_text,
        config=config,
        field_origin=demand.field_origin,
    )
    for event in guarded.events:
        payload = event.audit_payload()
        events.append(
            AuditEvent(
                "harness", payload["action"], payload["previous_value"], payload["new_value"]
            )
        )

    merged = _merge(demand, guarded.interpretation, requester_text, messages[-1], events)
    if current is S.RECEIVED:
        merged = _set_status(merged, S.PARSED, events)
    return _validate_and_route(merged, config, events)


def revalidate(demand: Demand, *, config: AppConfig) -> PipelineResult:
    """Roda regras e validação de novo, sem LLM (``POST /validate``, PATCH, confirmação de tipo)."""
    return _validate_and_route(demand, config, [])


# --- Merge (D06, D07, D27, D28) --------------------------------------------------------------


def _merge(
    demand: Demand,
    interpretation: LLMInterpretation,
    requester_text: str,
    last_message: str,
    events: list[AuditEvent],
) -> Demand:
    origin = dict(demand.field_origin)
    updates: dict[str, Any] = {}
    text = normalize(requester_text)

    # Campos extraídos: ausente mantém o anterior; novo substitui llm/message/rule, nunca manager.
    for name, raw in interpretation.extracted.provided().items():
        if origin.get(name) is MANAGER or not raw.strip():
            continue
        updates[name] = raw
        origin[name] = MESSAGE if normalize(raw).strip() in text else LLM

    # Classificação: não sobrescreve tipo do gestor nem tipo confirmado (D27).
    classification = interpretation.classification
    applied = not (demand.type_confirmed or origin.get("task_type") is MANAGER)
    events.append(
        AuditEvent(
            "llm",
            "classification",
            previous_value={
                "type": demand.task_type,
                "confidence": demand.classification_confidence,
            },
            new_value={
                "type": classification.type,
                "confidence": classification.confidence,
                "applied": applied,
            },
        )
    )
    if applied:
        updates["task_type"] = classification.type
        updates["classification_confidence"] = classification.confidence
        origin["task_type"] = LLM

    # Flag promocional do LLM gravada antes das regras, com origem llm (D28).
    if origin.get("is_promotional") is not MANAGER:
        updates["is_promotional"] = interpretation.is_promotional
        origin["is_promotional"] = LLM
    if interpretation.published_error is not None:  # D24; ausente mantém o anterior (D31)
        updates["published_error"] = interpretation.published_error

    dependencies = merge_dependencies(demand.dependencies, interpretation.dependencies)
    if dependencies != demand.dependencies:
        updates["dependencies"] = dependencies
    files = _merge_files(demand.required_files, interpretation.files)
    if files != demand.required_files:
        updates["required_files"] = files

    merged = Demand.model_validate({**demand.model_dump(), **updates, "field_origin": origin})
    merged = _drop_stale_dimensions(demand, merged, last_message, events)
    for name in updates:
        if name == "classification_confidence":
            continue
        before, after = getattr(demand, name), getattr(merged, name)
        before_origin, after_origin = demand.field_origin.get(name), origin.get(name)
        if before != after or before_origin != after_origin:
            events.append(
                AuditEvent(
                    "harness",
                    "field_registered",
                    previous_value=_field_payload(name, before, before_origin),
                    new_value=_field_payload(name, after, after_origin),
                )
            )
    return merged


def _drop_stale_dimensions(
    before: Demand, merged: Demand, last_message: str, events: list[AuditEvent]
) -> Demand:
    """Troca de formato apaga a dimensão de ``message``/``llm`` que a mensagem nova não repete.

    Assim o Rule Engine recalcula a dimensão para o formato novo (D28, D31). Formato que aparece
    pela primeira vez não é troca. Dimensão do gestor nunca é tocada; a de regra já é
    recalculada pelo próprio Rule Engine.
    """
    old_format, new_format = before.format, merged.format
    if not old_format or not new_format or normalize(old_format) == normalize(new_format):
        return merged
    dimensions = merged.dimensions
    dims_origin = merged.field_origin.get("dimensions")
    if not dimensions or dims_origin not in (MESSAGE, LLM):
        return merged
    if digit_groups(dimensions) <= digit_groups(last_message):
        return merged  # a mensagem nova traz (ou repete) a dimensão

    origin = dict(merged.field_origin)
    origin.pop("dimensions")
    events.append(
        AuditEvent(
            "harness",
            "field_cleared",
            previous_value=_field_payload("dimensions", dimensions, dims_origin),
            new_value={"field": "dimensions", "reason": "format_changed"},
        )
    )
    return merged.model_copy(update={"dimensions": None, "field_origin": origin})


def _merge_files(current: list[RequiredFile], new: list[str]) -> list[RequiredFile]:
    """Arquivos do LLM entram com origem llm, sem duplicar (D28)."""
    merged = list(current)
    seen = {normalize(f.name).strip() for f in current}
    for name in new:
        key = normalize(name).strip()
        if key and key not in seen:
            merged.append(RequiredFile(name=name.strip(), origin=LLM))
            seen.add(key)
    return merged


# --- Regras, validação e estado --------------------------------------------------------------


def _validate_and_route(
    demand: Demand, config: AppConfig, events: list[AuditEvent]
) -> PipelineResult:
    current = _set_status(demand, S.VALIDATING, events)

    ruled = apply_rules(current, config=config)
    for change in ruled.changes:
        payload = change.audit_payload()
        events.append(
            AuditEvent(
                "harness", payload["action"], payload["previous_value"], payload["new_value"]
            )
        )

    validation = validate_demand(ruled.demand, config=config)
    scored = ruled.demand.model_copy(
        update={
            "missing_information": validation.missing,
            "briefing_score": validation.score.score,
        }
    )
    events.append(
        AuditEvent(
            "harness",
            "briefing_score",
            previous_value={"score": demand.briefing_score},
            new_value={
                "score": validation.score.score,
                "band": validation.score.band,
                "missing": validation.missing,
            },
        )
    )

    if validation.ready:
        final = _set_status(scored, S.READY_FOR_TRIAGE, events)
        next_action: NextAction | None = None
    else:
        final = _set_status(scored, S.NEEDS_INFORMATION, events)
        next_action = (
            "CONFIRM_TYPE" if validation.needs_type_confirmation else "REQUEST_INFORMATION"
        )
    return PipelineResult(
        demand=final,
        questions=validation.questions,
        next_action=next_action,
        score_band=validation.score.band,
        events=events,
    )


def _set_status(demand: Demand, target: RequestStatus, events: list[AuditEvent]) -> Demand:
    new_status = transition(demand.status, target)
    events.append(
        AuditEvent(
            "harness",
            "status_transition",
            previous_value={"status": demand.status.value},
            new_value={"status": new_status.value},
        )
    )
    return demand.model_copy(update={"status": new_status})


# --- Auxiliares ------------------------------------------------------------------------------


def _local_date(now: datetime, tz: ZoneInfo) -> date:
    return now.astimezone(tz).date() if now.tzinfo else now.date()


def _known_fields(demand: Demand) -> dict[str, Any]:
    """Dados já registrados, em forma serializável, para o contexto do LLM (§8.1)."""
    names = [*EXTRACTABLE_FIELDS, "task_type"]
    return {
        name: to_jsonable_python(value)
        for name in names
        if (value := getattr(demand, name)) is not None
    }


def _field_payload(name: str, value: Any, origin: FieldOrigin | None) -> dict[str, Any]:
    return {
        "field": name,
        "value": to_jsonable_python(value),
        "origin": origin.value if origin else None,
    }
