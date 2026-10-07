"""Acciones que el agente puede proponer para resolver un incidente.

El agente solo las *propone*: ninguna herramienta modifica el sistema. Ejecutarlas
requiere siempre la aprobación de un humano (TONI-79).
"""

from typing import Literal

from pydantic import BaseModel, Field

ActionKind = Literal[
    "rollback",  # revertir un commit de código (redeploy de la versión anterior)
    "revert_config",  # revertir un cambio de config
    "restart",  # reiniciar un servicio o una dependencia (Postgres, Redis)
    "terminate_session",  # terminar una sesión de Postgres que bloquea
    "escalate",  # el problema es externo: escalar al responsable
]


class ActionOverride(BaseModel):
    """Corrección humana de la acción propuesta (p. ej. revertir otro commit)."""

    kind: ActionKind | None = None
    target: str | None = None


class ActionProposal(BaseModel):
    kind: ActionKind
    target: str = Field(description="Servicio, commit (SHA) o sesión sobre la que actuar")
    reason: str = Field(description="Por qué esta acción resuelve la causa raíz")
    evidence: list[str] = Field(description="Hechos concretos que la justifican")
    requires_approval: Literal[True] = True

    def corrected(self, override: ActionOverride | None, note: str = "") -> "ActionProposal":
        if override is None or (override.kind is None and override.target is None):
            return self
        changes = override.model_dump(exclude_none=True)
        reason = f"{self.reason} [corregida por un humano: {note or 'sin nota'}]"
        return self.model_copy(update=changes | {"reason": reason})
