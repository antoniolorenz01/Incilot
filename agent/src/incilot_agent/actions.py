"""Actions the agent can propose to resolve an incident.

The agent only *proposes* them: no tool modifies the system. Executing them always
requires a human's approval (TONI-79).
"""

from typing import Literal

from pydantic import BaseModel, Field

ActionKind = Literal[
    "rollback",  # revert a code commit (redeploy the previous version)
    "revert_config",  # revert a config change
    "restart",  # restart a service or a dependency (Postgres, Redis)
    "terminate_session",  # terminate a blocking Postgres session
    "escalate",  # the problem is external: escalate to the owner
]


class ActionOverride(BaseModel):
    """A human correction of the proposed action (e.g. revert a different commit)."""

    kind: ActionKind | None = None
    target: str | None = None


class ActionProposal(BaseModel):
    kind: ActionKind
    target: str = Field(description="Service, commit (SHA) or session to act on")
    reason: str = Field(description="Why this action resolves the root cause")
    evidence: list[str] = Field(description="Concrete facts that justify it")
    requires_approval: Literal[True] = True

    def corrected(self, override: ActionOverride | None, note: str = "") -> "ActionProposal":
        if override is None or (override.kind is None and override.target is None):
            return self
        changes = override.model_dump(exclude_none=True)
        reason = f"{self.reason} [corrected by a human: {note or 'no note'}]"
        return self.model_copy(update=changes | {"reason": reason})
