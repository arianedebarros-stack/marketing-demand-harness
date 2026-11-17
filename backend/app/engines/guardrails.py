"""Guardrails: sanitização da saída do LLM antes do merge (SPEC §8.2, D10, D27).

Função pura: recebe a interpretação, o texto do solicitante, a config e as origens atuais;
devolve uma interpretação limpa e a lista de eventos (descartes e ajustes) para o audit log.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

from app.core.config import AppConfig
from app.core.text import digit_groups, normalize, words
from app.schemas.demand import DATE_FIELDS, FieldOrigin
from app.schemas.llm import Classification, ExtractedFields, LLMInterpretation

NUMERIC_FIELDS = frozenset({"price", "quantity", "budget", "participants_count"})
ATTACHMENT_EXCEPTION_FIELDS = frozenset({"price"})  # §8.2: só price aceita "planilha/anexo"
TEMPORAL_FIELDS = DATE_FIELDS | {"validity"}  # D27: vigência também exige referência temporal
FALLBACK_TYPE = "Outro"

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True)
class GuardrailEvent:
    """Um descarte (``replacement is None``) ou ajuste feito pelo guardrail."""

    field: str
    value: Any
    reason: str
    replacement: Any = None

    def audit_payload(self) -> dict[str, Any]:
        return {
            "action": "guardrail_discard" if self.replacement is None else "guardrail_adjust",
            "previous_value": {"field": self.field, "value": self.value},
            "new_value": {"reason": self.reason, "replacement": self.replacement},
        }


@dataclass(frozen=True)
class GuardrailResult:
    interpretation: LLMInterpretation
    events: list[GuardrailEvent]


def apply_guardrails(
    interpretation: LLMInterpretation,
    *,
    requester_text: str,
    config: AppConfig,
    field_origin: Mapping[str, FieldOrigin],
) -> GuardrailResult:
    events: list[GuardrailEvent] = []
    checker = _TextChecker(requester_text, config)

    classification = _check_classification(interpretation.classification, config, events)

    for key, value in interpretation.extracted.unknown_keys().items():
        events.append(GuardrailEvent(key, value, "unknown_field"))

    kept: dict[str, str] = {}
    for name, value in interpretation.extracted.provided().items():
        if field_origin.get(name) is FieldOrigin.MANAGER:
            events.append(GuardrailEvent(name, value, "manager_field"))
            continue
        if name == "brand":
            brand = _canonical_brand(value, config)
            if brand is None:
                events.append(GuardrailEvent(name, value, "unknown_brand"))
                continue
            if brand != value:
                events.append(GuardrailEvent(name, value, "brand_canonicalized", brand))
            value = brand
        reason = checker.reject_reason(name, value)
        if reason:
            events.append(GuardrailEvent(name, value, reason))
            continue
        kept[name] = value

    sanitized = interpretation.model_copy(
        update={
            "classification": classification,
            "extracted": ExtractedFields.model_validate(kept),
        }
    )
    return GuardrailResult(interpretation=sanitized, events=events)


def _check_classification(
    classification: Classification, config: AppConfig, events: list[GuardrailEvent]
) -> Classification:
    allowed = {normalize(t): t for t in config.task_types.types}
    type_ = allowed.get(normalize(classification.type))
    if type_ is None:
        type_ = FALLBACK_TYPE
        events.append(GuardrailEvent("task_type", classification.type, "unknown_type", type_))

    confidence = min(max(classification.confidence, 0.0), 1.0)
    if confidence != classification.confidence:
        events.append(
            GuardrailEvent(
                "classification_confidence",
                classification.confidence,
                "confidence_clamped",
                confidence,
            )
        )
    return Classification(type=type_, confidence=confidence)


def _canonical_brand(value: str, config: AppConfig) -> str | None:
    target = normalize(value).strip()
    for brand in config.brands.values():
        if normalize(brand.name) == target:
            return brand.name
    return None


class _TextChecker:
    """Confere se um valor tem respaldo no texto do solicitante."""

    def __init__(self, text: str, config: AppConfig) -> None:
        rules = config.guardrails
        self._normalized = normalize(text)
        self._digits = digit_groups(text)
        self._words = words(text)
        self._min_word = rules.product_min_word_length
        attachment = {normalize(w) for w in rules.attachment_words}
        self._mentions_attachment = bool(attachment & self._words)
        self._has_temporal = any(
            re.search(pattern, self._normalized) for pattern in rules.temporal_patterns
        )

    def reject_reason(self, name: str, value: str) -> str | None:
        if name in NUMERIC_FIELDS and not self._number_ok(name, value):
            return "number_not_in_text"
        if name == "product" and not self._product_ok(value):
            return "product_not_in_text"
        if name in DATE_FIELDS and not _is_iso_date(value):
            return "invalid_date"
        if name in TEMPORAL_FIELDS and not self._has_temporal:
            return "no_temporal_reference"
        return None

    def _number_ok(self, name: str, value: str) -> bool:
        value_digits = digit_groups(value)
        if value_digits:
            # D10: os dígitos do valor precisam aparecer no texto (não basta haver dígitos).
            return value_digits <= self._digits
        # Sem dígitos (ex.: "Conforme planilha anexada"): só price, e com menção a anexo.
        return name in ATTACHMENT_EXCEPTION_FIELDS and self._mentions_attachment

    def _product_ok(self, value: str) -> bool:
        if self._mentions_attachment:
            return True
        return bool(words(value, self._min_word) & self._words)


def _is_iso_date(value: str) -> bool:
    if not _ISO_DATE_RE.match(value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True
