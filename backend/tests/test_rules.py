"""Rule Engine (SPEC §8.3, D28) — inclui AC07: Ferjá nunca recebe o CTA da Construjá."""

from typing import Any

import pytest

from app.core.config import AppConfig, load_app_config
from app.engines.rules import RuleChange, apply_rules
from app.schemas.demand import Demand, FieldOrigin

CONFIG: AppConfig = load_app_config()
BRANDS = CONFIG.brands
CONSTRUJA_CTA = BRANDS["construja"].mandatory_cta
FERJA_CTA = BRANDS["ferja"].mandatory_cta

M = FieldOrigin.MESSAGE
L = FieldOrigin.LLM
R = FieldOrigin.RULE
G = FieldOrigin.MANAGER


def _demand(origin: dict[str, FieldOrigin] | None = None, **fields: Any) -> Demand:
    """Demanda de teste. Campos passados sem origem explícita ficam com origem ``llm``."""
    content = {k: v for k, v in fields.items() if v is not None}
    base_origin = {k: L for k in content if k not in {"task_type", "is_promotional"}}
    return Demand(
        requester="Ana",
        department="Comercial",
        field_origin={**base_origin, **(origin or {})},
        **content,
    )


def _changed(changes: list[RuleChange]) -> dict[str, str]:
    return {c.field: c.rule for c in changes}


# --- AC07 · CTA por marca ------------------------------------------------------------------


def test_ferja_no_construja_cta() -> None:
    """AC07: a demanda Ferjá recebe o CTA Ferjá e nunca o da Construjá (caso 03)."""
    demand = _demand(
        task_type="Arte",
        brand="Ferjá",
        supplier="Krona",
        format="Feed",
        is_promotional=True,
    )

    result = apply_rules(demand, config=CONFIG)

    out = result.demand
    assert out.cta == FERJA_CTA
    assert out.cta != CONSTRUJA_CTA
    assert out.audience == "Consumidor final"
    assert out.message_tone == BRANDS["ferja"].tone
    assert out.field_origin["cta"] is R
    assert out.field_origin["audience"] is R


def test_brand_change_replaces_rule_cta() -> None:
    """Construjá → Ferjá: CTA, público e tom que vieram de regra são recalculados."""
    demand = _demand(
        origin={"cta": R, "audience": R, "message_tone": R},
        task_type="Arte",
        brand="Ferjá",
        cta=CONSTRUJA_CTA,
        audience=BRANDS["construja"].audience,
        message_tone=BRANDS["construja"].tone,
    )

    out = apply_rules(demand, config=CONFIG).demand

    assert out.cta == FERJA_CTA
    assert out.audience == BRANDS["ferja"].audience
    assert out.message_tone == BRANDS["ferja"].tone


def test_other_brand_cta_from_message_is_removed() -> None:
    """Mesmo vindo da mensagem, o CTA de outra marca nunca fica na demanda."""
    demand = _demand(origin={"cta": M}, task_type="Vídeo", brand="Ferjá", cta=CONSTRUJA_CTA)

    result = apply_rules(demand, config=CONFIG)

    assert result.demand.cta is None
    assert "cta" not in result.demand.field_origin
    assert _changed(result.changes)["cta"] == "foreign_brand_cta"


def test_mandatory_cta_replaces_message_cta() -> None:
    demand = _demand(origin={"cta": M}, task_type="Arte", brand="Construjá", cta="Compre já!")

    out = apply_rules(demand, config=CONFIG).demand

    assert out.cta == CONSTRUJA_CTA
    assert out.field_origin["cta"] is R


def test_brand_without_cta_clears_rule_cta() -> None:
    demand = _demand(origin={"cta": R}, task_type="Arte", brand="Construdigi", cta=CONSTRUJA_CTA)

    result = apply_rules(demand, config=CONFIG)

    assert BRANDS["construdigi"].mandatory_cta is None
    assert result.demand.cta is None
    assert "cta" not in result.demand.field_origin


def test_brand_without_cta_keeps_requester_cta() -> None:
    demand = _demand(origin={"cta": M}, task_type="Arte", brand="Construdigi", cta="Baixe o app")

    result = apply_rules(demand, config=CONFIG)

    assert result.demand.cta == "Baixe o app"
    assert "cta" not in _changed(result.changes)


@pytest.mark.parametrize("task_type", ["Arte", "Social Media", "Campanha", "Banner Site"])
def test_cta_applies_to_listed_types(task_type: str) -> None:
    out = apply_rules(_demand(task_type=task_type, brand="Construjá"), config=CONFIG).demand
    assert out.cta == CONSTRUJA_CTA


def test_cta_applies_to_any_type_when_promotional() -> None:
    demand = _demand(task_type="Vídeo", brand="Construjá", is_promotional=True)
    assert apply_rules(demand, config=CONFIG).demand.cta == CONSTRUJA_CTA


def test_cta_not_applied_outside_rule() -> None:
    demand = _demand(task_type="Vídeo", brand="Construjá")
    assert apply_rules(demand, config=CONFIG).demand.cta is None


def test_rule_cta_cleared_when_rule_no_longer_applies() -> None:
    demand = _demand(origin={"cta": R}, task_type="Relatório", brand="Construjá", cta=CONSTRUJA_CTA)

    result = apply_rules(demand, config=CONFIG)

    assert result.demand.cta is None
    assert _changed(result.changes)["cta"] == "rule_no_longer_applies"


def test_no_cta_without_brand() -> None:
    assert apply_rules(_demand(task_type="Arte"), config=CONFIG).demand.cta is None


# --- Canal ---------------------------------------------------------------------------------


def test_format_implies_channel() -> None:
    result = apply_rules(_demand(task_type="Arte", format="Feed"), config=CONFIG)

    assert result.demand.channel == "Instagram"
    assert result.demand.field_origin["channel"] is R
    assert _changed(result.changes)["channel"] == "format_implies_channel"


def test_format_does_not_override_channel_from_message() -> None:
    demand = _demand(origin={"channel": M}, task_type="Arte", format="Feed", channel="Facebook")

    out = apply_rules(demand, config=CONFIG).demand

    assert out.channel == "Facebook"
    assert out.dimensions == CONFIG.task_types.formats["facebook|feed"]


@pytest.mark.parametrize(("task_type", "channel"), [("Push", "App"), ("E-mail", "E-mail")])
def test_type_implies_channel(task_type: str, channel: str) -> None:
    result = apply_rules(_demand(task_type=task_type), config=CONFIG)

    assert result.demand.channel == channel
    assert _changed(result.changes)["channel"] == "type_implies_channel"


def test_type_does_not_override_channel_from_message() -> None:
    """D28: Push só preenche o canal vazio ou de regra."""
    demand = _demand(origin={"channel": M}, task_type="Push", channel="WhatsApp")
    assert apply_rules(demand, config=CONFIG).demand.channel == "WhatsApp"


def test_stale_rule_channel_is_cleared() -> None:
    """Canal derivado do formato some quando o formato deixa de implicar canal."""
    demand = _demand(origin={"channel": R}, task_type="Arte", format="Status", channel="Instagram")

    out = apply_rules(demand, config=CONFIG).demand

    assert out.channel is None
    assert "channel" not in out.field_origin


# --- Público e tom -------------------------------------------------------------------------


def test_brand_fills_audience_and_tone() -> None:
    out = apply_rules(_demand(task_type="Arte", brand="Construjá"), config=CONFIG).demand

    assert out.audience == "Lojistas"
    assert out.message_tone == BRANDS["construja"].tone


def test_brand_does_not_override_audience_from_message() -> None:
    demand = _demand(
        origin={"audience": M}, task_type="Arte", brand="Construjá", audience="Pintores"
    )

    out = apply_rules(demand, config=CONFIG).demand

    assert out.audience == "Pintores"
    assert out.message_tone == BRANDS["construja"].tone


def test_brand_removed_clears_rule_audience() -> None:
    demand = _demand(
        origin={"audience": R, "message_tone": R},
        task_type="Arte",
        audience="Lojistas",
        message_tone=BRANDS["construja"].tone,
    )

    out = apply_rules(demand, config=CONFIG).demand

    assert out.audience is None
    assert out.message_tone is None


# --- Dimensões -----------------------------------------------------------------------------


def test_case_02_feed_construja() -> None:
    """Caso 02: feed Construjá vira Instagram · Feed · 1080 × 1350 px, CTA e público da marca."""
    demand = _demand(task_type="Arte", brand="Construjá", supplier="Krona", format="Feed")

    out = apply_rules(demand, config=CONFIG).demand

    assert out.channel == "Instagram"
    assert out.dimensions == "1080 × 1350 px"
    assert out.audience == "Lojistas"
    assert out.cta == CONSTRUJA_CTA
    assert out.is_promotional is True


def test_dimensions_lookup_ignores_case_and_accents() -> None:
    demand = _demand(task_type="Arte", channel="INSTAGRAM", format="stories")
    assert apply_rules(demand, config=CONFIG).demand.dimensions == "1080 × 1920 px"


def test_dimensions_from_message_are_kept() -> None:
    demand = _demand(
        origin={"dimensions": M},
        task_type="Arte",
        channel="Instagram",
        format="Feed",
        dimensions="1080x1080",
    )
    assert apply_rules(demand, config=CONFIG).demand.dimensions == "1080 × 1080 px"


def test_rule_dimensions_follow_format_change() -> None:
    demand = _demand(
        origin={"dimensions": R},
        task_type="Arte",
        channel="Instagram",
        format="Stories",
        dimensions="1080 × 1350 px",
    )
    assert apply_rules(demand, config=CONFIG).demand.dimensions == "1080 × 1920 px"


def test_unknown_format_leaves_dimensions_empty() -> None:
    demand = _demand(task_type="Arte", channel="Site", format="Banner")
    assert apply_rules(demand, config=CONFIG).demand.dimensions is None


# --- Promocional e arquivos ----------------------------------------------------------------


@pytest.mark.parametrize("task_type", ["Arte", "Social Media"])
def test_supplier_makes_art_promotional(task_type: str) -> None:
    result = apply_rules(_demand(task_type=task_type, supplier="Krona"), config=CONFIG)

    assert result.demand.is_promotional is True
    assert result.demand.field_origin["is_promotional"] is R
    assert _changed(result.changes)["is_promotional"] == "supplier_promotional"


def test_supplier_does_not_make_video_promotional() -> None:
    out = apply_rules(_demand(task_type="Vídeo", supplier="Krona"), config=CONFIG).demand
    assert out.is_promotional is False
    assert out.required_files == []


def test_llm_promotional_flag_is_kept() -> None:
    out = apply_rules(_demand(task_type="Vídeo", is_promotional=True), config=CONFIG).demand
    assert out.is_promotional is True


def test_rule_promotional_flag_reverts_without_supplier() -> None:
    """Flag de regra (não do LLM) é recalculada: sem fornecedor, deixa de ser promocional."""
    demand = _demand(origin={"is_promotional": R}, task_type="Arte", is_promotional=True)

    result = apply_rules(demand, config=CONFIG)

    assert result.demand.is_promotional is False
    assert "is_promotional" not in result.demand.field_origin
    assert _changed(result.changes)["is_promotional"] == "rule_no_longer_applies"


def test_manager_promotional_flag_is_kept() -> None:
    demand = _demand(origin={"is_promotional": G}, task_type="Arte", supplier="Krona")

    result = apply_rules(demand, config=CONFIG)

    assert result.demand.is_promotional is False
    assert result.demand.required_files == []


def test_promotional_with_supplier_requires_files() -> None:
    demand = _demand(task_type="Arte", supplier="Krona")
    demand.required_files = ["Planilha de preços"]

    out = apply_rules(demand, config=CONFIG).demand

    assert out.required_files == ["Planilha de preços", "Logo Krona", "Imagens dos produtos"]


def test_promotional_without_supplier_requires_no_files() -> None:
    demand = _demand(task_type="Arte", is_promotional=True)
    assert apply_rules(demand, config=CONFIG).demand.required_files == []


# --- Propriedades gerais -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("field", "value", "extra"),
    [
        ("channel", "WhatsApp", {"format": "Feed"}),
        ("audience", "Diretoria", {}),
        ("message_tone", "Divertido", {}),
        ("cta", CONSTRUJA_CTA, {}),
        ("dimensions", "500 × 500 px", {"channel": "Instagram", "format": "Feed"}),
    ],
)
def test_manager_fields_are_never_touched(field: str, value: str, extra: dict[str, str]) -> None:
    demand = _demand(origin={field: G}, task_type="Arte", brand="Ferjá", **{field: value}, **extra)

    result = apply_rules(demand, config=CONFIG)

    assert getattr(result.demand, field) == value
    assert result.demand.field_origin[field] is G
    assert field not in _changed(result.changes)


def test_rules_are_idempotent() -> None:
    demand = _demand(task_type="Arte", brand="Construjá", supplier="Krona", format="Feed")

    first = apply_rules(demand, config=CONFIG)
    second = apply_rules(first.demand, config=CONFIG)

    assert second.changes == []
    assert second.demand == first.demand


def test_input_demand_is_not_mutated() -> None:
    demand = _demand(task_type="Arte", brand="Construjá", supplier="Krona", format="Feed")
    snapshot = demand.model_copy(deep=True)

    apply_rules(demand, config=CONFIG)

    assert demand == snapshot


def test_change_audit_payload() -> None:
    result = apply_rules(_demand(task_type="Arte", format="Feed"), config=CONFIG)
    change = next(c for c in result.changes if c.field == "channel")

    assert change.audit_payload() == {
        "action": "rule_applied",
        "previous_value": {"field": "channel", "value": None},
        "new_value": {"rule": "format_implies_channel", "value": "Instagram"},
    }
