"""Dependency Checker: dependências explícitas, bloqueio e resolução (SPEC §8.7, D03, D34).

Funções puras. Só entram dependências que o LLM extraiu de menções explícitas; o harness não
inventa nenhuma. A tarefa nasce com ``blocked = true`` se houver alguma ``Pendente``.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app.core.text import normalize
from app.schemas.demand import Dependency

PENDING = "Pendente"
RESOLVED = "Resolvida"


def dependency_key(text: str) -> str:
    """Texto normalizado: sem acento, sem caixa, sem pontuação e com espaços simples."""
    return " ".join(re.findall(r"[a-z0-9]+", normalize(text)))


def merge_dependencies(
    current: Sequence[Dependency], new: Sequence[Dependency]
) -> list[Dependency]:
    """Acrescenta as novas sem duplicar; as existentes ficam como estão (inclusive o status)."""
    merged = list(current)
    seen = {dependency_key(d.dependency) for d in current}
    for dep in new:
        key = dependency_key(dep.dependency)
        if key and key not in seen:
            merged.append(dep)
            seen.add(key)
    return merged


def pending_dependencies(dependencies: Sequence[Dependency]) -> list[Dependency]:
    return [d for d in dependencies if d.status == PENDING]


def is_blocked(dependencies: Sequence[Dependency]) -> bool:
    """D03: a tarefa fica bloqueada enquanto houver dependência pendente."""
    return bool(pending_dependencies(dependencies))


@dataclass(frozen=True)
class DependencyResolution:
    dependencies: list[Dependency]
    index: int
    previous: Dependency
    changed: bool

    @property
    def blocked(self) -> bool:
        return is_blocked(self.dependencies)

    def audit_payload(self) -> dict[str, Any]:
        return {
            "action": "dependency_resolved",
            "previous_value": {"index": self.index, **self.previous.model_dump()},
            "new_value": {"index": self.index, "status": RESOLVED, "blocked": self.blocked},
        }


def resolve_dependency(dependencies: Sequence[Dependency], index: int) -> DependencyResolution:
    """Marca a dependência ``index`` como resolvida (``POST .../dependencies/{i}/resolve``)."""
    if not 0 <= index < len(dependencies):
        raise IndexError(f"dependência {index} não existe (total: {len(dependencies)})")
    previous = dependencies[index]
    updated = [d.model_copy() for d in dependencies]
    if previous.status != RESOLVED:
        updated[index] = previous.model_copy(update={"status": RESOLVED})
    return DependencyResolution(
        dependencies=updated,
        index=index,
        previous=previous,
        changed=previous.status != RESOLVED,
    )
