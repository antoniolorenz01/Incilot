"""El resultado de una investigación."""

from typing import Literal

from pydantic import BaseModel, Field

from incilot_agent.actions import ActionProposal


class Diagnosis(BaseModel):
    service: str = Field(description="Servicio o componente donde está la causa raíz")
    root_cause: str = Field(description="Qué está fallando y por qué, en una o dos frases")
    culprit_commit: str | None = Field(
        description="SHA del commit que lo causó, si hay uno; null si es externo o de infra"
    )
    evidence: list[str] = Field(description="Hechos concretos observados que lo demuestran")
    confidence: Literal["low", "medium", "high"]
    plan: list[str] = Field(
        description="Pasos para resolver el incidente y verificar que se resolvió"
    )
    action: ActionProposal
