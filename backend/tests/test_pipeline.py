"""Pipeline: interpretação → guardrails → merge → regras → validação → estado (SPEC §7, T10).

AC06 (memória entre mensagens), caso 01, proteção do ``task_type`` do gestor ou confirmado
(D27) e ``is_promotional`` do LLM gravado antes das regras (D28).
"""

from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from app.core.config import AppConfig, load_app_config
from app.core.state_machine import InvalidTransition
from app.llm.base import InterpretationContext
from app.llm.fake_client import FakeLLMClient
from app.schemas.audit import AuditEvent
from app.schemas.demand import Demand, Dependency, FieldOrigin, RequestStatus, RequiredFile
from app.schemas.llm import LLMInterpretation
from app.services.pipeline import PipelineResult, process_message, revalidate

CONFIG: AppConfig = load_app_config()
TZ = ZoneInfo("America/Sao_Paulo")
NOW = datetime(2026, 10, 19, 9, 0, tzinfo=TZ)  # segunda-feira de manhã (D20)
TOMORROW = date(2026, 10, 20)
NEXT_FRIDAY = date(2026, 10, 23)
CONSTRUJA = CONFIG.brands["construja"]

M = FieldOrigin.MESSAGE
L = FieldOrigin.LLM
R = FieldOrigin.RULE
G = FieldOrigin.MANAGER
S = RequestStatus

CASE_02 = (
    "Preciso de um feed 1080x1350 da Construjá para divulgar a promoção Krona amanhã. "
    "Os produtos e preços estão na planilha anexada e a promoção vale até sexta."
)
CASE_06 = (
    "Preciso de uma arte da Krona para amanhã.",
    "Construjá",
    "Instagram feed. São 3 produtos da planilha anexada. Promoção válida até sexta. "
    "Ainda aguardando aprovação de preço por Compras.",
)


class ScriptedLLM:
    """LLM de teste: devolve interpretações prontas e guarda os contextos recebidos."""

    provider = "scripted"

    def __init__(self, *interpretations: LLMInterpretation) -> None:
        self._queue = list(interpretations)
        self.contexts: list[InterpretationContext] = []

    def interpret(self, context: InterpretationContext) -> LLMInterpretation:
        self.contexts.append(context)
        return self._queue.pop(0)


def _interp(
    extracted: dict[str, Any] | None = None,
    type_: str = "Arte",
    confidence: float = 0.92,
    **extra: Any,
) -> LLMInterpretation:
    return LLMInterpretation.model_validate(
        {
            "classification": {"type": type_, "confidence": confidence},
            "extracted": extracted or {},
            **extra,
        }
    )


def _new() -> Demand:
    return Demand(requester="Ana", department="Comercial")


def _run(demand: Demand, messages: list[str], llm: Any | None = None) -> PipelineResult:
    return process_message(
        demand, messages, llm=llm or FakeLLMClient(), config=CONFIG, now=NOW, tz=TZ
    )


def _conversation(*messages: str) -> PipelineResult:
    demand, history = _new(), []
    result: PipelineResult | None = None
    for message in messages:
        history.append(message)
        result = _run(demand, history)
        demand = result.demand
    assert result is not None
    return result


def _actions(events: list[AuditEvent]) -> list[str]:
    return [e.action for e in events]


# --- Caso 01 -------------------------------------------------------------------------------


def test_case_01_needs_information() -> None:
    """Caso 01: não cria tarefa; NEEDS_INFORMATION; pergunta o que falta."""
    result = _run(_new(), ["Faz uma arte da Krona."])

    assert result.demand.status is S.NEEDS_INFORMATION
    assert result.next_action == "REQUEST_INFORMATION"
    assert [q.fields for q in result.questions] == [
        ["brand"],
        ["objective"],
        ["channel", "format"],
        ["product", "price"],
        ["validity"],
        ["deadline"],
    ]
    assert result.demand.external_task_id is None
    assert result.demand.supplier == "Krona"
    assert result.demand.task_type == "Arte"
    assert result.demand.missing_information == [
        "brand",
        "objective",
        "audience",
        "message_tone",
        "deadline",
        "channel",
        "format",
        "product",
        "price",
        "validity",
    ]
    assert result.demand.briefing_score < 100


def test_case_01_state_path() -> None:
    result = _run(_new(), ["Faz uma arte da Krona."])

    transitions = [e.new_value for e in result.events if e.action == "status_transition"]
    assert transitions == [
        {"status": "PARSED"},
        {"status": "VALIDATING"},
        {"status": "NEEDS_INFORMATION"},
    ]


# --- Caso 02 -------------------------------------------------------------------------------


def test_case_02_complete_in_one_message() -> None:
    result = _run(_new(), [CASE_02])
    demand = result.demand

    assert demand.status is S.READY_FOR_TRIAGE
    assert result.questions == []
    assert result.score_band == "Pronto para produção"
    assert demand.briefing_score == 100
    assert demand.missing_information == []
    assert (demand.task_type, demand.brand, demand.supplier) == ("Arte", "Construjá", "Krona")
    assert (demand.channel, demand.format) == ("Instagram", "Feed")
    assert demand.dimensions == "1080 × 1350 px"
    assert demand.deadline == TOMORROW
    assert demand.cta == CONSTRUJA.mandatory_cta


# --- AC06 · memória entre mensagens --------------------------------------------------------


def test_memory_across_answers() -> None:
    """AC06 (caso 06): dados de mensagens anteriores são mantidos até 100%."""
    first = _conversation(CASE_06[0])
    assert first.demand.status is S.NEEDS_INFORMATION
    assert first.demand.deadline == TOMORROW

    second = _conversation(*CASE_06[:2])
    assert second.demand.brand == "Construjá"
    assert second.demand.deadline == TOMORROW
    assert second.demand.audience == CONSTRUJA.audience
    assert {f for q in second.questions for f in q.fields} == {
        "objective",
        "channel",
        "format",
        "product",
        "price",
        "validity",
    }

    final = _conversation(*CASE_06)
    demand = final.demand
    assert demand.status is S.READY_FOR_TRIAGE
    assert demand.briefing_score == 100
    assert demand.brand == "Construjá"
    assert demand.supplier == "Krona"
    assert demand.deadline == TOMORROW
    assert demand.validity == NEXT_FRIDAY.isoformat()
    assert (demand.channel, demand.format) == ("Instagram", "Feed")
    assert demand.dependencies == [
        Dependency(dependency="Aprovação de preço", owner="Compras", status="Pendente")
    ]


def test_absent_field_keeps_previous_value() -> None:
    """D06: campo ausente na nova interpretação mantém o valor anterior."""
    llm = ScriptedLLM(
        _interp({"brand": "Ferjá", "objective": "Divulgar a linha nova"}),
        _interp({"channel": "Instagram"}),
    )
    first = _run(_new(), ["Arte da Ferjá para divulgar a linha nova"], llm)
    second = _run(first.demand, ["Arte da Ferjá para divulgar a linha nova", "Instagram"], llm)

    assert second.demand.brand == "Ferjá"
    assert second.demand.objective == "Divulgar a linha nova"
    assert second.demand.channel == "Instagram"


def test_new_value_replaces_llm_message_and_rule() -> None:
    demand = _new().model_copy(
        update={
            "objective": "Antigo",
            "channel": "Facebook",
            "audience": "Pintores",
            "field_origin": {"objective": L, "channel": M, "audience": R},
        }
    )
    text = "Objetivo novo no WhatsApp para Lojistas"
    llm = ScriptedLLM(
        _interp({"objective": "Objetivo novo", "channel": "WhatsApp", "audience": "Lojistas"})
    )

    out = _run(demand, [text], llm).demand

    assert (out.objective, out.channel, out.audience) == ("Objetivo novo", "WhatsApp", "Lojistas")


def test_blank_value_does_not_erase_previous_value() -> None:
    demand = _new().model_copy(update={"objective": "Divulgar", "field_origin": {"objective": L}})
    llm = ScriptedLLM(_interp({"objective": "   "}))

    assert _run(demand, ["Divulgar"], llm).demand.objective == "Divulgar"


def test_manager_field_is_never_overwritten() -> None:
    demand = _new().model_copy(update={"objective": "Do gestor", "field_origin": {"objective": G}})
    llm = ScriptedLLM(_interp({"objective": "Divulgar outra coisa"}))

    result = _run(demand, ["Divulgar outra coisa"], llm)

    assert result.demand.objective == "Do gestor"
    assert result.demand.field_origin["objective"] is G
    assert "guardrail_discard" in _actions(result.events)


def test_origin_message_vs_llm() -> None:
    """D07: ``message`` quando o valor está no texto (sem acento/caixa); senão ``llm``."""
    result = _run(_new(), [CASE_02])
    origin = result.demand.field_origin

    assert origin["brand"] is M  # "Construjá" aparece no texto
    assert origin["format"] is M  # "feed"
    assert origin["deadline"] is L  # "2026-10-20" foi calculado a partir de "amanhã"
    assert origin["product"] is L  # "Conforme planilha anexada" é inferido
    assert origin["task_type"] is L
    assert origin["channel"] is R  # feed → Instagram (Rule Engine)


def test_context_has_known_and_asked_fields() -> None:
    """§8.1: o LLM recebe os dados já registrados e os campos perguntados por último."""
    llm = ScriptedLLM(_interp({"supplier": "Krona"}), _interp({"brand": "Construjá"}))
    first = _run(_new(), ["Faz uma arte da Krona."], llm)
    _run(first.demand, ["Faz uma arte da Krona.", "Construjá"], llm)

    first_ctx, second_ctx = llm.contexts
    assert first_ctx.asked_fields == []
    assert first_ctx.today == NOW.date()
    assert second_ctx.known_fields["supplier"] == "Krona"
    assert second_ctx.messages == ["Faz uma arte da Krona.", "Construjá"]
    assert second_ctx.asked_fields == [f for q in first.questions for f in q.fields]


# --- D27 · task_type do gestor ou confirmado -----------------------------------------------


@pytest.mark.parametrize(
    "protection",
    [
        {"field_origin": {"task_type": G}},
        {"type_confirmed": True, "field_origin": {"task_type": L}},
    ],
    ids=["manager", "type_confirmed"],
)
def test_protected_task_type_is_not_overwritten(protection: dict[str, Any]) -> None:
    """D27: classificação do LLM não sobrescreve tipo do gestor ou confirmado."""
    demand = _new().model_copy(
        update={"task_type": "Vídeo", "classification_confidence": 0.5, **protection}
    )
    llm = ScriptedLLM(_interp(type_="Arte", confidence=0.99))

    result = _run(demand, ["Faz uma arte."], llm)

    assert result.demand.task_type == "Vídeo"
    assert result.demand.classification_confidence == 0.5
    assert result.demand.field_origin["task_type"] is protection["field_origin"]["task_type"]
    event = next(e for e in result.events if e.action == "classification")
    assert event.new_value == {"type": "Arte", "confidence": 0.99, "applied": False}


def test_unprotected_task_type_follows_llm() -> None:
    demand = _new().model_copy(
        update={
            "task_type": "Vídeo",
            "classification_confidence": 0.9,
            "field_origin": {"task_type": L},
        }
    )
    llm = ScriptedLLM(_interp(type_="Arte", confidence=0.95))

    out = _run(demand, ["Na verdade é uma arte."], llm).demand

    assert (out.task_type, out.classification_confidence) == ("Arte", 0.95)


def test_low_confidence_asks_to_confirm_type() -> None:
    """§7: confiança < 0,70 → NEEDS_INFORMATION, missing = ["task_type"], CONFIRM_TYPE."""
    result = _run(_new(), ["Faz promoção da Krona."])

    assert result.demand.classification_confidence < CONFIG.task_types.classification_threshold
    assert result.demand.status is S.NEEDS_INFORMATION
    assert result.demand.missing_information == ["task_type"]
    assert result.next_action == "CONFIRM_TYPE"
    assert [q.fields for q in result.questions] == [["task_type"]]


# --- D28 · is_promotional do LLM antes das regras ------------------------------------------


def test_llm_promotional_flag_is_saved_before_rules() -> None:
    """D28: o merge grava o is_promotional do LLM (origem llm) e as regras o enxergam."""
    llm = ScriptedLLM(_interp({"brand": "Construjá"}, type_="Vídeo", is_promotional=True))

    result = _run(_new(), ["Vídeo da Construjá para a promoção"], llm)

    demand = result.demand
    assert demand.is_promotional is True
    assert demand.field_origin["is_promotional"] is L
    # Vídeo só recebe CTA quando promocional: prova que a regra viu a flag do LLM.
    assert demand.cta == CONSTRUJA.mandatory_cta

    actions = _actions(result.events)
    flag = next(
        i
        for i, e in enumerate(result.events)
        if e.action == "field_registered" and e.new_value["field"] == "is_promotional"
    )
    assert flag < actions.index("rule_applied")


def test_rules_mark_promotional_when_llm_does_not() -> None:
    llm = ScriptedLLM(_interp({"supplier": "Krona"}, type_="Arte", is_promotional=False))

    demand = _run(_new(), ["Arte da Krona"], llm).demand

    assert demand.is_promotional is True
    assert demand.field_origin["is_promotional"] is R


def test_llm_flag_false_clears_previous_llm_flag() -> None:
    """A flag do LLM vem do histórico inteiro: a interpretação nova substitui a anterior."""
    demand = _new().model_copy(
        update={"task_type": "Vídeo", "is_promotional": True, "field_origin": {"is_promotional": L}}
    )
    llm = ScriptedLLM(_interp(type_="Vídeo", is_promotional=False))

    assert _run(demand, ["Vídeo institucional"], llm).demand.is_promotional is False


def test_llm_files_become_required_files_with_llm_origin() -> None:
    llm = ScriptedLLM(
        _interp({"supplier": "Krona"}, files=["Planilha de preços"]),
        _interp({"supplier": "Krona"}, files=["Planilha de preços", "planilha de PREÇOS"]),
    )
    first = _run(_new(), ["Arte da Krona com planilha"], llm)
    second = _run(first.demand, ["Arte da Krona com planilha", "ok"], llm)

    files = [(f.name, f.origin) for f in second.demand.required_files]
    assert files == [
        ("Planilha de preços", L),
        ("Logo Krona", R),
        ("Imagens dos produtos", R),
    ]


def test_llm_dependencies_are_added_once_and_keep_status() -> None:
    resolved = Dependency(dependency="Aprovação de preço", owner="Compras", status="Resolvida")
    demand = _new().model_copy(update={"dependencies": [resolved]})
    llm = ScriptedLLM(
        _interp(
            dependencies=[
                {"dependency": "aprovação de preço", "owner": "Compras"},
                {"dependency": "Fotos do produto", "owner": "Krona"},
            ]
        )
    )

    out = _run(demand, ["Aguardando fotos do produto pela Krona"], llm).demand

    assert out.dependencies == [
        resolved,
        Dependency(dependency="Fotos do produto", owner="Krona", status="Pendente"),
    ]


def _with_published_error() -> Demand:
    return _new().model_copy(update={"published_error": True})


def test_published_error_explicit_true_is_saved() -> None:
    """D24/D26: a flag fica na demanda para a triagem (T11) recalcular a prioridade."""
    llm = ScriptedLLM(_interp(published_error=True))
    assert _run(_new(), ["Saiu com erro"], llm).demand.published_error is True


@pytest.mark.parametrize(
    "interpretation",
    [_interp(), _interp(published_error=None)],
    ids=["ausente", "vazio"],
)
def test_published_error_absent_keeps_previous(interpretation: LLMInterpretation) -> None:
    """D31: sem valor explícito na interpretação nova, a flag anterior fica."""
    result = _run(_with_published_error(), ["Mais um detalhe"], ScriptedLLM(interpretation))

    assert result.demand.published_error is True
    assert not any(
        e.action == "field_registered" and e.new_value["field"] == "published_error"
        for e in result.events
    )


def test_published_error_explicit_false_clears_previous() -> None:
    llm = ScriptedLLM(_interp(published_error=False))
    assert _run(_with_published_error(), ["Não houve erro"], llm).demand.published_error is False


def test_fake_does_not_touch_published_error() -> None:
    """O Fake nunca preenche a flag (D26), então ela não é apagada entre mensagens."""
    assert _run(_with_published_error(), [CASE_02]).demand.published_error is True


def test_message_in_pending_approval_goes_back_to_validating_keeping_locks() -> None:
    """§7: nova mensagem em PENDING_APPROVAL volta a VALIDATING, mantendo as travas."""
    ready = _run(_new(), [CASE_02]).demand
    pending = ready.model_copy(
        update={
            "status": S.PENDING_APPROVAL,
            "priority": "Alta",
            "priority_locked": True,
            "assigned_to": "designer-a",
            "assignment_locked": True,
        }
    )

    result = _run(pending, [CASE_02, "Troca para stories."])

    transitions = [e.new_value["status"] for e in result.events if e.action == "status_transition"]
    assert transitions == ["VALIDATING", "READY_FOR_TRIAGE"]
    out = result.demand
    assert out.format == "Stories"
    # D28/D31: o formato mudou e a mensagem nova não traz dimensão → a regra recalcula.
    assert out.dimensions == "1080 × 1920 px"
    assert out.field_origin["dimensions"] is R
    assert (out.priority_locked, out.assignment_locked) == (True, True)
    assert (out.priority, out.assigned_to) == ("Alta", "designer-a")


# --- Troca de formato e dimensão (D28, D31) ------------------------------------------------


def _format_change(new_message: str, dims_origin: FieldOrigin = M) -> PipelineResult:
    first = _run(_new(), [CASE_02]).demand
    assert (first.dimensions, first.field_origin["dimensions"]) == ("1080 × 1350 px", M)
    demand = first.model_copy(
        update={
            "status": S.NEEDS_INFORMATION,
            "field_origin": {**first.field_origin, "dimensions": dims_origin},
        }
    )
    return _run(demand, [CASE_02, new_message])


def test_format_change_drops_message_dimensions() -> None:
    result = _format_change("Troca para stories.")

    assert result.demand.dimensions == "1080 × 1920 px"
    assert result.demand.field_origin["dimensions"] is R
    cleared = next(e for e in result.events if e.action == "field_cleared")
    assert cleared.previous_value == {
        "field": "dimensions",
        "value": "1080 × 1350 px",
        "origin": "message",
    }
    assert cleared.new_value == {"field": "dimensions", "reason": "format_changed"}
    actions = _actions(result.events)
    assert actions.index("field_cleared") < actions.index("rule_applied")


@pytest.mark.parametrize(
    ("last_message", "kept"),
    [("Troca para stories.", False), ("Troca para stories 1080x1350.", True)],
)
def test_format_change_drops_llm_dimensions(last_message: str, kept: bool) -> None:
    """D31: a dimensão inferida pelo LLM também sai na troca de formato, salvo se repetida."""
    demand = _new().model_copy(
        update={
            "status": S.NEEDS_INFORMATION,
            "task_type": "Arte",
            "classification_confidence": 0.92,
            "channel": "Instagram",
            "format": "Feed",
            "dimensions": "1080 × 1350 px",
            "field_origin": {"task_type": L, "channel": R, "format": M, "dimensions": L},
        }
    )
    llm = ScriptedLLM(_interp({"format": "Stories"}))

    result = _run(demand, [last_message], llm)

    if kept:
        assert result.demand.dimensions == "1080 × 1350 px"
        assert result.demand.field_origin["dimensions"] is L
        assert "field_cleared" not in _actions(result.events)
    else:
        assert result.demand.dimensions == "1080 × 1920 px"
        assert result.demand.field_origin["dimensions"] is R
        cleared = next(e for e in result.events if e.action == "field_cleared")
        assert cleared.previous_value["origin"] == "llm"


def test_format_change_with_new_dimensions_keeps_them() -> None:
    result = _format_change("Troca para stories 1080x1920.")

    assert result.demand.dimensions == "1080 × 1920 px"
    assert result.demand.field_origin["dimensions"] is M
    assert "field_cleared" not in _actions(result.events)


def test_format_change_restating_old_dimensions_keeps_them() -> None:
    """Se a mensagem nova repete a dimensão, ela é do solicitante e fica."""
    result = _format_change("Troca para stories, mas mantém 1080x1350.")

    assert result.demand.format == "Stories"
    assert result.demand.dimensions == "1080 × 1350 px"
    assert result.demand.field_origin["dimensions"] is M


def test_format_change_never_touches_manager_dimensions() -> None:
    result = _format_change("Troca para stories.", dims_origin=G)

    assert result.demand.dimensions == "1080 × 1350 px"
    assert result.demand.field_origin["dimensions"] is G
    assert "field_cleared" not in _actions(result.events)


def test_first_format_keeps_message_dimensions() -> None:
    """Formato que aparece pela primeira vez não é troca: a dimensão da mensagem fica."""
    first = _run(_new(), ["Arte 1080x1080 da Construjá para divulgar a promoção Krona"])
    assert first.demand.format is None

    out = _run(
        first.demand,
        ["Arte 1080x1080 da Construjá para divulgar a promoção Krona", "No feed."],
    ).demand

    assert out.format == "Feed"
    assert (out.dimensions, out.field_origin["dimensions"]) == ("1080 × 1080 px", M)


def test_same_format_keeps_message_dimensions() -> None:
    result = _format_change("Mantém o feed, só confirma o prazo.")

    assert result.demand.dimensions == "1080 × 1350 px"
    assert "field_cleared" not in _actions(result.events)


@pytest.mark.parametrize(
    "status",
    [S.READY_FOR_TRIAGE, S.TRIAGED, S.APPROVED, S.TASK_CREATED, S.CANCELLED, S.REJECTED, S.ERROR],
)
def test_message_in_other_states_is_rejected(status: RequestStatus) -> None:
    demand = _new().model_copy(update={"status": status})
    llm = ScriptedLLM(_interp())

    with pytest.raises(InvalidTransition):
        _run(demand, ["Mais uma coisa"], llm)
    assert llm.contexts == []  # o LLM nem é chamado


def test_revalidate_without_llm() -> None:
    """POST /validate (D01): roda regras e validação de novo, sem chamar o LLM."""
    waiting = _run(_new(), ["Faz uma arte da Krona."]).demand
    edited = waiting.model_copy(
        update={
            "brand": "Construjá",
            "objective": "Divulgar promoção Krona",
            "channel": "Instagram",
            "format": "Feed",
            "product": "Conforme planilha anexada",
            "price": "Conforme planilha anexada",
            "validity": "2026-10-23",
            "deadline": TOMORROW,
            "field_origin": {**waiting.field_origin, "brand": G},
        }
    )

    result = revalidate(edited, config=CONFIG)

    assert result.demand.status is S.READY_FOR_TRIAGE
    assert result.demand.audience == CONSTRUJA.audience
    assert result.next_action is None
    assert "interpretation" not in _actions(result.events)


# --- Audit ---------------------------------------------------------------------------------


def test_audit_events_cover_each_step() -> None:
    """§15: recebimento, interpretação, classificação, campos, guardrails, regras, score e
    transições geram eventos."""
    llm = ScriptedLLM(
        _interp({"brand": "Construjá", "price": "R$ 9,90", "format": "Feed"}, type_="Arte")
    )

    result = _run(_new(), ["Feed da Construjá"], llm)
    actions = _actions(result.events)

    for action in (
        "message_received",
        "interpretation",
        "classification",
        "field_registered",
        "guardrail_discard",
        "rule_applied",
        "briefing_score",
        "status_transition",
    ):
        assert action in actions
    assert actions[0] == "message_received"
    interpretation = next(e for e in result.events if e.action == "interpretation")
    assert interpretation.actor == "llm"
    assert interpretation.new_value["provider"] == "scripted"
    discard = next(e for e in result.events if e.action == "guardrail_discard")
    assert discard.previous_value == {"field": "price", "value": "R$ 9,90"}


def test_unchanged_fields_are_not_registered_again() -> None:
    first = _run(_new(), [CASE_02])
    second = _run(first.demand.model_copy(update={"status": S.NEEDS_INFORMATION}), [CASE_02])

    assert "field_registered" not in _actions(second.events)


def test_input_demand_is_not_mutated() -> None:
    demand = _new()
    snapshot = demand.model_copy(deep=True)

    _run(demand, [CASE_02])

    assert demand == snapshot


def test_requester_files_keep_their_origin() -> None:
    demand = _new().model_copy(
        update={"required_files": [RequiredFile(name="Logo Krona", origin=M)]}
    )
    llm = ScriptedLLM(_interp({"supplier": "Krona"}))

    out = _run(demand, ["Arte da Krona"], llm).demand

    assert [(f.name, f.origin) for f in out.required_files] == [
        ("Logo Krona", M),
        ("Imagens dos produtos", R),
    ]
