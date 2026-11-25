"""FakeLLMClient: interpretação determinística por regras, sem rede (SPEC §12).

Simula o LLM para testes e uso offline. As palavras-chave abaixo são a "inteligência" simulada
do modelo (§12), não regras de negócio: marcas e fornecedores vêm do contexto (config/).
Como o LLM real, só extrai; quem decide é o harness.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from app.core.text import normalize
from app.llm.base import InterpretationContext
from app.schemas.demand import Dependency
from app.schemas.llm import Classification, ExtractedFields, LLMInterpretation

# --- Palavras-chave (§12) ---------------------------------------------------------------------

# Ordem importa: a primeira regra que casar define o tipo.
TYPE_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Banner Site", (r"\bbanner\b.*\bsite\b|\bsite\b.*\bbanner\b",)),
    ("Vídeo", (r"\bvideos?\b", r"\bgravar\b")),
    ("Evento", (r"\beventos?\b", r"\bfeiras?\b")),
    ("Material Impresso", (r"\bfolhetos?\b", r"\bcartaz(es)?\b", r"\bimpressos?\b")),
    ("Arte", (r"\bartes?\b", r"\bpecas?\b", r"\bfeed\b", r"\bstories\b", r"\bcarross[eé]is\b",
              r"\bcarrossel\b")),
    ("Social Media", (r"\bposts?\b",)),
    ("Campanha", (r"\bcampanhas?\b",)),
)  # fmt: skip
ONE_RULE_CONFIDENCE = 0.92
MANY_RULES_CONFIDENCE = 0.80
PROMO_ONLY = ("Arte", 0.55)
NOTHING = ("Outro", 0.40)

CHANNELS = {
    "instagram": "Instagram",
    "whatsapp": "WhatsApp",
    "facebook": "Facebook",
    "linkedin": "LinkedIn",
    "site": "Site",
    "app": "App",
    "e-mail": "E-mail",
    "email": "E-mail",
}
FORMATS = {"feed": "Feed", "stories": "Stories", "reels": "Reels", "carrossel": "Carrossel"}

# Erros pequenos de digitação em canal e formato (D41): uma letra a mais, a menos, trocada ou
# duas vizinhas invertidas ("instragram"). Só para palavras-chave longas, para "gmail", "sitio"
# ou "reais" não virarem E-mail, Site ou Reels.
TYPO_MIN_LENGTH = 6
TYPO_MAX_DISTANCE = 1

ATTACHMENT_VALUE = "Conforme planilha anexada"
OBJECTIVE_VERBS = r"divulgar|promover|anunciar|lan[cç]ar"
DEFAULT_OWNER = "Não informado"

_WEEKDAYS = {"segunda": 0, "terca": 1, "quarta": 2, "quinta": 3, "sexta": 4, "sabado": 5,
             "domingo": 6}  # fmt: skip
_DATE_EXPR = (
    r"hoje|amanha|(?:segunda|terca|quarta|quinta|sexta|sabado|domingo)|\d{1,2}/\d{1,2}(?:/\d{2,4})?"  # noqa: E501
)
_DATE_RE = re.compile(rf"\b(?:{_DATE_EXPR})\b")
_VALIDITY_RE = re.compile(
    rf"\b(?:vale|valida|validade|vigencia|vigente)\b[^.;!?]*?\bate\s+(?:o dia\s+|dia\s+)?(?P<date>{_DATE_EXPR})\b"  # noqa: E501
)
_DIMENSIONS_RE = re.compile(r"\b\d{3,4}\s*[x×]\s*\d{3,4}\b", re.IGNORECASE)
_ATTACHMENT_RE = re.compile(r"\b(planilha|anexo|anexad[oa]s?|anexei)\b")
_PROMO_RE = re.compile(r"\bpromoc(ao|oes)\b")

_OWNER = r"(?:\s+(?:por|pel[oa]|com|d[oa])\s+(?P<owner>[A-ZÀ-Ý][\wÀ-ÿ]*))?\s*(?:[.;!?,]|$)"
_DEPENDENCY_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(rf"(?i:aguardando)\s+(?P<what>.+?){_OWNER}"), "{what}"),
    (re.compile(rf"(?i:depende(?:mos)?\s+d[eoa])\s+(?P<what>.+?){_OWNER}"), "{what}"),
    (re.compile(rf"(?i:falta)\s+(?P<what>(?i:aprova[cç][aã]o).*?){_OWNER}"), "{what}"),
    (
        re.compile(
            rf"(?i:ainda\s+n[aã]o\s+(?:foi\s+|foram\s+)?aprovad[oa]s?)\s+(?P<what>.+?){_OWNER}"
        ),  # noqa: E501
        "Aprovação de {what}",
    ),
)
_ARTICLE_RE = re.compile(r"^(?:o|a|os|as)\s+", re.IGNORECASE)
_TEMPORAL_CUT_RE = re.compile(
    r"\s+(?:para\s+)?(?:hoje|amanh[aã]|at[eé]\b|segunda|ter[cç]a|quarta|quinta|sexta|s[aá]bado"
    r"|domingo|\d{1,2}/\d{1,2}).*$",
    re.IGNORECASE,
)


def _normalize(text: str) -> str:
    """Sem acento, minúsculas e sem o sufixo '-feira' (evita confundir com 'feira')."""
    return re.sub(r"\b(segunda|terca|quarta|quinta|sexta)[- ]feira\b", r"\1", normalize(text))


def _capitalize(text: str) -> str:
    return text[:1].upper() + text[1:]


def _strip_end(text: str) -> str:
    return text.strip().rstrip(".;!?,").strip()


# --- Datas -----------------------------------------------------------------------------------


def _resolve_date(expr: str, today: date) -> date | None:
    if expr == "hoje":
        return today
    if expr == "amanha":
        return today + timedelta(days=1)
    if expr in _WEEKDAYS:
        # D11: próxima ocorrência a partir de amanhã.
        days = (_WEEKDAYS[expr] - today.weekday()) % 7 or 7
        return today + timedelta(days=days)
    parts = [int(p) for p in expr.split("/")]
    day, month = parts[0], parts[1]
    year = parts[2] if len(parts) == 3 else today.year
    if year < 100:
        year += 2000
    try:
        resolved = date(year, month, day)
    except ValueError:
        return None
    if len(parts) == 2 and resolved < today:
        # D11: dd/mm que já passou vai para o ano seguinte.
        try:
            resolved = date(year + 1, month, day)
        except ValueError:
            return None
    return resolved


# --- Extração de uma mensagem -----------------------------------------------------------------


def _typo_distance(a: str, b: str) -> int:
    """Distância de edição com transposição de vizinhas (Damerau, alinhamento ótimo)."""
    previous2: list[int] = []
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            value = min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + cost)
            if i > 1 and j > 1 and ca == b[j - 2] and a[i - 2] == cb:
                value = min(value, previous2[j - 2] + 1)
            current.append(value)
        previous2, previous = previous, current
    return previous[-1]


def _find_keyword(normalized: str, keywords: dict[str, str]) -> str | None:
    """Palavra exata primeiro; só sem ela, a aproximada (D41). Vale a ordem de ``keywords``."""
    for key, value in keywords.items():
        if re.search(rf"\b{re.escape(key)}\b", normalized):
            return value
    words = re.findall(r"[a-z0-9]+", normalized)
    for key, value in keywords.items():
        if len(key) < TYPO_MIN_LENGTH:
            continue
        if any(_typo_distance(word, key) <= TYPO_MAX_DISTANCE for word in words):
            return value
    return None


def _find_name(normalized: str, names: list[str]) -> str | None:
    for name in names:
        if re.search(rf"\b{re.escape(_normalize(name))}\b", normalized):
            return name
    return None


def _extract_message(text: str, context: InterpretationContext) -> dict[str, str]:
    norm = _normalize(text)
    found: dict[str, str] = {}

    if brand := _find_name(norm, context.brand_names):
        found["brand"] = brand
    if supplier := _find_name(norm, context.suppliers):
        found["supplier"] = supplier
    if channel := _find_keyword(norm, CHANNELS):
        found["channel"] = channel
    if fmt := _find_keyword(norm, FORMATS):
        found["format"] = fmt
    if dimensions := _DIMENSIONS_RE.search(text):
        found["dimensions"] = dimensions.group(0)
    if _ATTACHMENT_RE.search(norm):
        found["product"] = ATTACHMENT_VALUE
        found["price"] = ATTACHMENT_VALUE

    # Vigência antes do prazo: o trecho da vigência sai do texto usado para achar o prazo.
    remaining = norm
    if validity := _VALIDITY_RE.search(norm):
        resolved = _resolve_date(validity.group("date"), context.today)
        if resolved:
            found["validity"] = resolved.isoformat()
        remaining = norm[: validity.start()] + " " + norm[validity.end() :]
    for match in _DATE_RE.finditer(remaining):
        if resolved := _resolve_date(match.group(0), context.today):
            found["deadline"] = resolved.isoformat()
            break

    if objective := re.search(rf"\b(?:{OBJECTIVE_VERBS})\b\s+[^.;!?]+", text, re.IGNORECASE):
        value = _strip_end(_TEMPORAL_CUT_RE.sub("", objective.group(0)))
        if value:
            found["objective"] = _capitalize(value)
    return found


def _extract_dependencies(text: str) -> list[Dependency]:
    dependencies: list[Dependency] = []
    for pattern, template in _DEPENDENCY_PATTERNS:
        for match in pattern.finditer(text):
            what = _ARTICLE_RE.sub("", match.group("what").strip())
            description = _capitalize(template.format(what=what))
            owner = match.group("owner")
            if not owner:
                owner = "Compras" if re.search(r"\bpre[cç]os?\b", what, re.I) else DEFAULT_OWNER
            dependencies.append(Dependency(dependency=description, owner=owner))
    return dependencies


# --- Classificação ---------------------------------------------------------------------------


def _classify(normalized_history: str) -> Classification:
    matched = [
        type_name
        for type_name, patterns in TYPE_RULES
        if any(re.search(p, normalized_history) for p in patterns)
    ]
    if matched:
        confidence = ONE_RULE_CONFIDENCE if len(matched) == 1 else MANY_RULES_CONFIDENCE
        return Classification(type=matched[0], confidence=confidence)
    type_name, confidence = PROMO_ONLY if _PROMO_RE.search(normalized_history) else NOTHING
    return Classification(type=type_name, confidence=confidence)


# --- Cliente ---------------------------------------------------------------------------------


class FakeLLMClient:
    provider = "fake"

    def interpret(self, context: InterpretationContext) -> LLMInterpretation:
        messages = [m for m in context.messages if m.strip()]
        normalized_history = " \n ".join(_normalize(m) for m in messages)

        extracted: dict[str, str] = {}
        dependencies: dict[str, Dependency] = {}
        last: dict[str, str] = {}
        for message in messages:
            last = _extract_message(message, context)
            extracted.update(last)  # mensagem mais recente vence
            for dep in _extract_dependencies(message):
                dependencies.setdefault(_normalize(dep.dependency), dep)

        is_promotional = bool(_PROMO_RE.search(normalized_history))
        if "objective" not in extracted and is_promotional and "supplier" in extracted:
            extracted["objective"] = f"Divulgar promoção {extracted['supplier']}"

        # §12: nada novo na última resposta e só um campo perguntado → a resposta é o valor.
        if messages and len(context.asked_fields) == 1 and not self._has_new(last, context):
            extracted[context.asked_fields[0]] = _strip_end(messages[-1])

        return LLMInterpretation(
            classification=_classify(normalized_history),
            extracted=ExtractedFields.model_validate(extracted),
            is_promotional=is_promotional,
            dependencies=list(dependencies.values()),
        )

    @staticmethod
    def _has_new(found: dict[str, str], context: InterpretationContext) -> bool:
        return any(str(context.known_fields.get(k)) != v for k, v in found.items())
