"""Saída exigida do LLM (SPEC §8.1).

O schema só garante a forma. Conteúdo (tipo permitido, confiança em [0,1], datas ISO, marca
existente, chaves desconhecidas) é tratado em ``engines/guardrails.py`` (§8.2), que registra
cada descarte no audit log. Por isso os valores de ``extracted`` chegam como texto cru.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.demand import Dependency


class Classification(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: str
    confidence: float


class ExtractedFields(BaseModel):
    """Mesmos campos de ``demand.ContentFields`` (``EXTRACTABLE_FIELDS``), todos como texto.

    Chaves desconhecidas são preservadas em ``model_extra`` para o guardrail descartar e auditar.
    """

    model_config = ConfigDict(
        extra="allow",
        coerce_numbers_to_str=True,
        json_schema_extra={"additionalProperties": False},
    )

    company: str | None = None
    brand: str | None = None
    campaign: str | None = None
    supplier: str | None = None
    objective: str | None = None
    audience: str | None = None
    message_tone: str | None = None
    channel: str | None = None
    format: str | None = None
    dimensions: str | None = None
    product: str | None = None
    price: str | None = None
    validity: str | None = None
    cta: str | None = None
    deadline: str | None = None
    duration: str | None = None
    concept: str | None = None
    location: str | None = None
    participants: str | None = None
    shoot_date: str | None = None
    headline: str | None = None
    landing_page: str | None = None
    link: str | None = None
    publish_period: str | None = None
    size: str | None = None
    quantity: str | None = None
    material: str | None = None
    finishing: str | None = None
    event_name: str | None = None
    event_date: str | None = None
    event_time: str | None = None
    participants_count: str | None = None
    budget: str | None = None
    deliverables: str | None = None

    def provided(self) -> dict[str, str]:
        """Campos conhecidos que vieram com valor."""
        return {
            name: value
            for name in type(self).model_fields
            if (value := getattr(self, name)) is not None
        }

    def unknown_keys(self) -> dict[str, Any]:
        return dict(self.model_extra or {})


class LLMInterpretation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    classification: Classification
    extracted: ExtractedFields
    is_promotional: bool = False
    # None = o LLM não disse nada; só um valor explícito muda a flag da demanda (D31).
    published_error: bool | None = None
    dependencies: list[Dependency] = Field(default_factory=list)
    files: list[str] = Field(default_factory=list)

    @classmethod
    def tool_input_schema(cls) -> dict[str, Any]:
        """JSON Schema autocontido (sem ``$ref``) para o ``input_schema`` da tool (§8.1)."""
        schema = cls.model_json_schema()
        defs = schema.pop("$defs", {})
        inlined: dict[str, Any] = _inline_refs(schema, defs)
        return inlined


def _inline_refs(node: Any, defs: dict[str, Any]) -> Any:
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str):
            target = defs[ref.removeprefix("#/$defs/")]
            extra = {k: v for k, v in node.items() if k != "$ref"}
            return _inline_refs({**target, **extra}, defs)
        return {key: _inline_refs(value, defs) for key, value in node.items()}
    if isinstance(node, list):
        return [_inline_refs(item, defs) for item in node]
    return node
