"""Evento de auditoria ainda não gravado (SPEC §15).

Engines e o pipeline produzem eventos; ``services/audit.py`` os grava em ``audit_log``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.schemas.api import AuditActor


@dataclass(frozen=True)
class AuditEvent:
    """Linha de ``audit_log`` ainda não gravada (§15)."""

    actor: AuditActor
    action: str
    previous_value: dict[str, Any] = field(default_factory=dict)
    new_value: dict[str, Any] = field(default_factory=dict)
