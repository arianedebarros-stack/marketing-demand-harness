"""Briefing Score: percentual de obrigatórios preenchidos e faixa (SPEC §8.4, D29).

Função pura: recebe as contagens e a config; as faixas vêm de ``task_types.json``.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from app.core.config import AppConfig
from app.schemas.api import ScoreBand


@dataclass(frozen=True)
class BriefingScore:
    score: int
    band: ScoreBand
    filled: int
    total: int


def compute_briefing_score(filled: int, total: int, *, config: AppConfig) -> BriefingScore:
    """``round(filled / total × 100)`` com meio para cima; 100 só com tudo preenchido (D29)."""
    if total <= 0:
        raise ValueError("total de obrigatórios deve ser positivo")
    if not 0 <= filled <= total:
        raise ValueError(f"preenchidos fora do intervalo: {filled} de {total}")

    percent = Decimal(filled * 100) / Decimal(total)
    score = int(percent.quantize(Decimal(1), rounding=ROUND_HALF_UP))
    if filled < total:
        score = min(score, 99)  # 99,5% não pode virar "Pronto para produção"

    band = next(b.band for b in config.task_types.score_bands if score >= b.min)
    return BriefingScore(score=score, band=band, filled=filled, total=total)
