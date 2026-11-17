"""Rule Engine: regras de negócio de config/ aplicadas à demanda (SPEC §8.3, D28).

Função pura: recebe a demanda (já com a interpretação mesclada) e a config; devolve uma nova
demanda e a lista de mudanças para o audit log. A demanda de entrada não é alterada.

Critério de sobrescrita (D28):
- Campo com origem ``manager`` nunca é tocado.
- Campos derivados (canal, público, tom, dimensões) só são preenchidos quando estão vazios ou já
  vieram de regra. Um valor de regra que deixou de valer é apagado.
- O CTA obrigatório da marca substitui valores de ``llm`` e ``message``. Um CTA igual ao de outra
  marca é sempre removido.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.config import AppConfig, Brand
from app.core.text import normalize
from app.schemas.demand import Demand, FieldOrigin

RULE = FieldOrigin.RULE
MANAGER = FieldOrigin.MANAGER


@dataclass(frozen=True)
class RuleChange:
    """Uma mudança feita por regra; ``value is None`` quando o valor foi apagado."""

    field: str
    previous: Any
    value: Any
    rule: str

    def audit_payload(self) -> dict[str, Any]:
        return {
            "action": "rule_applied",
            "previous_value": {"field": self.field, "value": self.previous},
            "new_value": {"rule": self.rule, "value": self.value},
        }


@dataclass(frozen=True)
class RuleResult:
    demand: Demand
    changes: list[RuleChange]


def apply_rules(demand: Demand, *, config: AppConfig) -> RuleResult:
    work = _Work(demand)
    task_types = config.task_types
    rules = task_types.rules
    task_type = demand.task_type
    brand = _find_brand(demand.brand, config)

    promotional = _apply_promotional(work, demand, rules.supplier_promo_types)

    # 1–2. Canal: o tipo (Push, E-mail) prevalece sobre o formato, pois é a regra posterior.
    type_channel = rules.type_implies_channel.get(task_type) if task_type else None
    format_channel = _lookup(task_types.format_implies_channel, demand.format)
    if type_channel:
        work.derive("channel", type_channel, "type_implies_channel")
    else:
        work.derive("channel", format_channel, "format_implies_channel")

    # 3. Público e tom da marca.
    work.derive("audience", brand.audience if brand else None, "brand_audience")
    work.derive("message_tone", brand.tone if brand else None, "brand_tone")

    # 4. CTA obrigatório da marca.
    cta_applies = brand is not None and (promotional or task_type in rules.cta_types)
    _apply_cta(work, brand, brand.mandatory_cta if brand and cta_applies else None, config)

    # 5. Dimensões por canal + formato.
    channel, format_ = work.get("channel"), demand.format
    dimensions = (
        _lookup(task_types.formats, f"{channel}|{format_}") if channel and format_ else None
    )
    work.derive("dimensions", dimensions, "format_dimensions")

    # 6. Arquivos obrigatórios de promoção com fornecedor.
    if promotional and demand.supplier:
        files = list(demand.required_files)
        for template in rules.promo_supplier_files:
            file = template.format(supplier=demand.supplier)
            if file not in files:
                files.append(file)
        if files != demand.required_files:
            work.set(
                "required_files",
                files,
                "promo_supplier_files",
                origin=work.origin("required_files"),
            )

    return RuleResult(demand=work.build(), changes=work.changes)


def _apply_promotional(work: _Work, demand: Demand, supplier_types: list[str]) -> bool:
    """``is_promotional = llm.is_promotional OR (supplier AND task_type ∈ supplier_types)``."""
    origin = demand.field_origin.get("is_promotional")
    if origin is MANAGER:
        return demand.is_promotional
    # Se a flag veio de regra, o LLM não a marcou: recalcula do zero.
    from_llm = demand.is_promotional and origin is not RULE
    by_supplier = bool(demand.supplier) and demand.task_type in supplier_types
    promotional = from_llm or by_supplier
    if promotional != demand.is_promotional:
        if promotional:
            work.set("is_promotional", True, "supplier_promotional", origin=RULE)
        else:
            work.set("is_promotional", False, "rule_no_longer_applies", origin=None)
    return promotional


def _apply_cta(work: _Work, brand: Brand | None, desired: str | None, config: AppConfig) -> None:
    origin = work.origin("cta")
    current = work.get("cta")
    if origin is MANAGER:
        return
    if desired is not None:
        if current != desired or origin is not RULE:
            work.set("cta", desired, "brand_cta", origin=RULE)
        return
    if current is None:
        return
    if origin is RULE:
        work.set("cta", None, "rule_no_longer_applies", origin=None)
    elif brand is not None and _is_foreign_cta(current, brand, config):
        work.set("cta", None, "foreign_brand_cta", origin=None)


def _is_foreign_cta(cta: str, brand: Brand, config: AppConfig) -> bool:
    target = normalize(cta).strip()
    return any(
        other.mandatory_cta and normalize(other.mandatory_cta).strip() == target
        for other in config.brands.values()
        if other.name != brand.name
    )


def _find_brand(name: str | None, config: AppConfig) -> Brand | None:
    if not name:
        return None
    target = normalize(name).strip()
    return next((b for b in config.brands.values() if normalize(b.name) == target), None)


def _lookup(table: dict[str, str], key: str | None) -> str | None:
    """Busca em tabela de config com chave comparada sem acento e sem caixa."""
    if not key:
        return None
    target = normalize(key).strip()
    return next((v for k, v in table.items() if normalize(k) == target), None)


class _Work:
    """Cópia de trabalho da demanda: acumula valores, origens e mudanças."""

    def __init__(self, demand: Demand) -> None:
        self._demand = demand
        self._values: dict[str, Any] = {}
        self._origin = dict(demand.field_origin)
        self.changes: list[RuleChange] = []

    def get(self, field: str) -> Any:
        return self._values[field] if field in self._values else getattr(self._demand, field)

    def origin(self, field: str) -> FieldOrigin | None:
        return self._origin.get(field)

    def set(self, field: str, value: Any, rule: str, *, origin: FieldOrigin | None) -> None:
        self.changes.append(RuleChange(field, self.get(field), value, rule))
        self._values[field] = value
        if origin is None:
            self._origin.pop(field, None)
        else:
            self._origin[field] = origin

    def derive(self, field: str, desired: str | None, rule: str) -> None:
        """Preenche campo derivado: só se vazio ou de regra; apaga valor de regra obsoleto."""
        origin, current = self.origin(field), self.get(field)
        if origin is MANAGER or (current is not None and origin is not RULE):
            return
        if desired is None:
            if current is not None:
                self.set(field, None, "rule_no_longer_applies", origin=None)
            return
        if current != desired or origin is not RULE:
            self.set(field, desired, rule, origin=RULE)

    def build(self) -> Demand:
        return self._demand.model_copy(
            update={**self._values, "field_origin": self._origin}, deep=True
        )
