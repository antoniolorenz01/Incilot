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


class ActionProposal(BaseModel):
    kind: ActionKind
    target: str = Field(description="Servicio, commit (SHA) o sesión sobre la que actuar")
    reason: str = Field(description="Por qué esta acción resuelve la causa raíz")
    evidence: list[str] = Field(description="Hechos concretos que la justifican")
    requires_approval: Literal[True] = True
