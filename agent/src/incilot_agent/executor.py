"""Execution of human-approved actions, with interchangeable connectors.

The LLM never executes anything: it has no tool for it. The graph's `execute` node
calls the executor only after human approval.

    SimulationExecutor  the simulated mini-company (operations service, with a token)
    NoopExecutor        executes nothing (dry_run and tests)
    (GitHubExecutor)    optional: open a revert PR in a real repo
"""

from typing import Literal, Protocol

import httpx
from pydantic import BaseModel

from incilot_agent import config
from incilot_agent.actions import ActionProposal


class ExecutionResult(BaseModel):
    status: Literal["executed", "failed", "skipped"]
    detail: str
    connector: str


class Executor(Protocol):
    name: str

    async def execute(self, action: ActionProposal) -> ExecutionResult: ...


class NoopExecutor:
    name = "noop"

    async def execute(self, action: ActionProposal) -> ExecutionResult:
        return ExecutionResult(
            status="skipped",
            detail=f"not executed ({action.kind} {action.target})",
            connector=self.name,
        )


class SimulationExecutor:
    """Asks the mini-company's operations service to execute the action."""

    name = "simulation"

    def __init__(self, url: str, token: str):
        self.url = url
        self.token = token

    async def execute(self, action: ActionProposal) -> ExecutionResult:
        async with httpx.AsyncClient(timeout=60) as http:
            response = await http.post(
                self.url,
                json={"kind": action.kind, "target": action.target},
                headers={"x-ops-token": self.token},
            )
        if response.status_code != 200:
            return ExecutionResult(
                status="failed",
                detail=f"HTTP {response.status_code}: {response.text[:200]}",
                connector=self.name,
            )
        return ExecutionResult(**response.json(), connector=self.name)


def default_executor() -> Executor:
    if config.OPS_URL and config.OPS_TOKEN:
        return SimulationExecutor(config.OPS_URL, config.OPS_TOKEN)
    return NoopExecutor()
