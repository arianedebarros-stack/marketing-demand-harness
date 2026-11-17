"""Utilitários de texto puros, compartilhados por engines e clientes de LLM."""

from __future__ import annotations

import re
import unicodedata


def normalize(text: str) -> str:
    """Sem acento e em minúsculas (comparações de marca, tipo, palavras)."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()


def digit_groups(text: str) -> set[str]:
    """Sequências de dígitos do texto: 'R$ 19,90' → {'19', '90'}."""
    return set(re.findall(r"\d+", text))


def words(text: str, min_length: int = 1) -> set[str]:
    """Palavras normalizadas (só letras) com pelo menos ``min_length`` letras."""
    return {w for w in re.findall(r"[a-z]+", normalize(text)) if len(w) >= min_length}
