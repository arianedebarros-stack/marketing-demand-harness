"""Duplicidade: tarefa aberta parecida antes de criar uma nova (SPEC §8.8, D12, D34).

Função pura: recebe a demanda, o título calculado, as tarefas existentes (lidas do banco por quem
chama), a config e o "agora". A API usa o resultado para responder 409 (caso 05).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from app.core.config import AppConfig
from app.core.text import normalize
from app.schemas.demand import Demand

SAME_SUPPLIER = "same_brand_type_supplier"
SAME_CAMPAIGN = "same_brand_type_campaign"
SIMILAR_TITLE = "similar_title"


@dataclass(frozen=True)
class ExistingTask:
    id: int
    title: str
    brand: str | None
    task_type: str | None
    supplier: str | None
    campaign: str | None
    created_at: datetime
    is_open: bool


@dataclass(frozen=True)
class DuplicateMatch:
    task: ExistingTask
    criteria: list[str]
    jaccard: float


@dataclass(frozen=True)
class DedupeResult:
    matches: list[DuplicateMatch] = field(default_factory=list)

    @property
    def duplicate(self) -> ExistingTask | None:
        """A candidata mais forte, ou None."""
        return self.matches[0].task if self.matches else None

    def audit_payload(self) -> dict[str, Any]:
        if not self.matches:
            return {"action": "no_duplicate", "new_value": {}}
        best = self.matches[0]
        return {
            "action": "duplicate_found",
            "new_value": {
                "task_id": best.task.id,
                "title": best.task.title,
                "criteria": list(best.criteria),
                "jaccard": round(best.jaccard, 4),
                "candidates": [m.task.id for m in self.matches],
            },
        }


def title_words(title: str) -> set[str]:
    """Palavras do título sem acento/caixa; o separador "|" some (D12) e números contam (D34)."""
    return set(re.findall(r"[a-z0-9]+", normalize(title)))


def title_jaccard(a: str, b: str) -> float:
    words_a, words_b = title_words(a), title_words(b)
    union = words_a | words_b
    return len(words_a & words_b) / len(union) if union else 0.0


def find_duplicate(
    demand: Demand,
    *,
    title: str,
    tasks: Sequence[ExistingTask],
    config: AppConfig,
    now: datetime,
) -> DedupeResult:
    rules = config.dedupe
    window = timedelta(days=rules.window_days)
    matches: list[DuplicateMatch] = []
    for task in tasks:
        if not task.is_open:
            continue
        criteria: list[str] = []
        recent = now - task.created_at <= window
        if recent and _same(demand.brand, task.brand) and _same(demand.task_type, task.task_type):
            if _same(demand.supplier, task.supplier):
                criteria.append(SAME_SUPPLIER)
            if _same(demand.campaign, task.campaign):
                criteria.append(SAME_CAMPAIGN)
        jaccard = title_jaccard(title, task.title)
        if jaccard >= rules.title_jaccard_min:
            criteria.append(SIMILAR_TITLE)
        if criteria:
            matches.append(DuplicateMatch(task=task, criteria=criteria, jaccard=jaccard))

    # Mais forte primeiro: critério de marca/tipo, depois Jaccard, depois a mais recente.
    matches.sort(
        key=lambda m: (
            SAME_SUPPLIER not in m.criteria and SAME_CAMPAIGN not in m.criteria,
            -m.jaccard,
            -m.task.created_at.timestamp(),
        )
    )
    return DedupeResult(matches=matches)


def _same(a: str | None, b: str | None) -> bool:
    """Igualdade sem acento/caixa; ``null == null`` não conta (D12)."""
    if not a or not b or not a.strip() or not b.strip():
        return False
    return normalize(a).strip() == normalize(b).strip()
