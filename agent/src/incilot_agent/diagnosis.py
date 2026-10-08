"""The result of an investigation."""

from typing import Literal

from pydantic import BaseModel, Field

from incilot_agent.actions import ActionProposal


class Diagnosis(BaseModel):
    service: str = Field(description="Service or component where the root cause lies")
    root_cause: str = Field(description="What is failing and why, in one or two sentences")
    culprit_commit: str | None = Field(
        description="SHA of the commit that caused it, if any; null if external or infrastructure"
    )
    evidence: list[str] = Field(description="Concrete observed facts that prove it")
    confidence: Literal["low", "medium", "high"]
    plan: list[str] = Field(
        description="Steps to resolve the incident and verify that it was resolved"
    )
    action: ActionProposal
