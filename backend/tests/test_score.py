"""AC08 — Briefing Score (SPEC §8.4, D29)."""

import pytest

from app.core.config import AppConfig, load_app_config
from app.engines.score import compute_briefing_score
from app.engines.validator import validate_demand
from app.schemas.demand import Demand

CONFIG: AppConfig = load_app_config()


def test_six_of_eight_is_75_percent() -> None:
    """AC08: Arte não promocional tem 8 obrigatórios; com 6 preenchidos, o score é 75%."""
    demand = Demand(
        requester="Ana",
        department="Comercial",
        task_type="Arte",
        classification_confidence=0.95,
        brand="Construjá",
        objective="Divulgar a linha de tintas",
        audience="Lojistas",
        message_tone="Comercial",
        channel="Instagram",
        # faltam format e deadline
    )

    result = validate_demand(demand, config=CONFIG)

    assert len(result.required) == 8
    assert result.missing == ["deadline", "format"]
    assert result.score.filled == 6
    assert result.score.total == 8
    assert result.score.score == 75
    assert result.score.band == "Parcial"


def test_score_function_six_of_eight() -> None:
    score = compute_briefing_score(6, 8, config=CONFIG)
    assert (score.score, score.band) == (75, "Parcial")


@pytest.mark.parametrize(
    ("filled", "total", "expected", "band"),
    [
        (0, 6, 0, "Incompleto"),
        (49, 100, 49, "Incompleto"),
        (50, 100, 50, "Parcial"),
        (79, 100, 79, "Parcial"),
        (80, 100, 80, "Quase pronto"),
        (99, 100, 99, "Quase pronto"),
        (100, 100, 100, "Pronto para produção"),
        (11, 11, 100, "Pronto para produção"),
    ],
)
def test_score_bands(filled: int, total: int, expected: int, band: str) -> None:
    score = compute_briefing_score(filled, total, config=CONFIG)
    assert (score.score, score.band) == (expected, band)


@pytest.mark.parametrize(
    ("filled", "total", "expected"),
    [(1, 8, 13), (5, 8, 63), (3, 8, 38), (2, 3, 67), (1, 3, 33)],
)
def test_score_rounds_half_up(filled: int, total: int, expected: int) -> None:
    """D29: arredondamento comercial (meio para cima), não o arredondamento bancário."""
    assert compute_briefing_score(filled, total, config=CONFIG).score == expected


def test_almost_complete_is_never_100() -> None:
    """199/200 = 99,5% arredondaria para 100; só 100% de fato é 'Pronto para produção'."""
    score = compute_briefing_score(199, 200, config=CONFIG)
    assert (score.score, score.band) == (99, "Quase pronto")


@pytest.mark.parametrize(("filled", "total"), [(0, 0), (-1, 5), (6, 5)])
def test_invalid_counts_raise(filled: int, total: int) -> None:
    with pytest.raises(ValueError):
        compute_briefing_score(filled, total, config=CONFIG)
