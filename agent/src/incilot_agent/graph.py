"""The investigation graph.

    triage ──► agent ⇄ tools ──► finish ───────────┐
                 └──────────────► force_diagnosis ─┴──► approval (pause)
                                  (step or token limit)

- triage: system overview without an LLM (triage.py).
- agent: the LLM decides which tool to use or, once it has the root cause with
  evidence, calls `submit_diagnosis`.
- tools: runs the read-only tools and returns the results.
- finish / force_diagnosis: put the structured diagnosis into the state.
- approval: pauses the graph (interrupt) until a human approves or rejects the
  proposed action. The state lives in the checkpointer: it resumes from another process.

With a checkpointer (Postgres in production) every step is saved: an investigation
cut off halfway resumes from the last completed step.
"""

import asyncio
import operator
import os
from datetime import UTC, datetime
from typing import Annotated, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import StructuredTool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import interrupt
from pydantic import ValidationError

from incilot_agent.actions import ActionOverride, ActionProposal
from incilot_agent.diagnosis import Diagnosis
from incilot_agent.executor import Executor, NoopExecutor
from incilot_agent.llm import invoke_with_fallback, model_name
from incilot_agent.tools import READ_ONLY_TOOLS
from incilot_agent.tools._guard import fit_to_budget
from incilot_agent.triage import overview
from incilot_agent.verification import NullRecorder, NullVerifier

MAX_STEPS = int(os.getenv("AGENT_MAX_STEPS", "12"))
# Claude Code (local, on a subscription) spends ~3x the tokens per round: each call is a
# fresh `claude -p` with the tools as text, and every cached token is counted in full.
_DEFAULT_MAX_TOKENS = "450000" if os.getenv("LLM_PROVIDER") == "claude-code" else "150000"
MAX_TOKENS = int(os.getenv("AGENT_MAX_TOKENS", _DEFAULT_MAX_TOKENS))
# Cap on what the tools return in one round (~4 characters per token).
ROUND_BUDGET_CHARS = int(os.getenv("AGENT_ROUND_BUDGET_CHARS", "16000"))
SUBMIT = "submit_diagnosis"

SYSTEM_PROMPT = """\
You are the on-call engineer (SRE) for an online shop. There is an incident in progress
and you have to find the root cause with evidence and propose an action to resolve it.

The shop has 4 services: shop (the entry point: it orchestrates orders by calling users,
inventory and payments), users, inventory and payments; they use Postgres and Redis. Every
merge to main in the company repo is deployed automatically.

How to investigate:
1. Locate the origin, not just the symptom: if a dependency fails, the one complaining is
   shop (timeouts, 502). Follow the chain to the service or component that is failing.
2. Form hypotheses and test them with evidence: metrics, logs, commits, config and the
   database (pg_stat_activity and pg_locks for sessions and locks). With
   search_knowledge you find runbooks, docs and the relevant code by topic.
3. Review recent changes, but do not assume the latest commit is the culprit: relate
   the content of the change to the symptom and to the moment it started.
4. There is background noise: isolated transient errors and one-off spikes happen all the
   time and are not the incident. Look for what changed in a sustained way. The initial
   triage already compares each metric with its baseline and marks log errors as NEW,
   GROWING or stable: stable ones existed before the incident and do not explain it. If
   the alert says since when, focus on what started or changed from that moment on:
   anything earlier may belong to another incident that has already been resolved.
5. The cause may be external (a provider) or infrastructure, with no culprit commit.

Use only data you obtained with the tools; do not make anything up. Write every text
field of the diagnosis in British English. Once you have the root cause with evidence,
finish by calling submit_diagnosis."""


class State(TypedDict):
    alert: str
    since: str | None  # when the incident started (ISO 8601), if the alert says so
    messages: Annotated[list, add_messages]
    steps: int
    tokens: int
    diagnosis: dict | None
    stop_reason: str | None
    approval: dict | None  # {"approved": bool, "by": str, "note": str, "action": override}
    approved_action: dict | None  # the action to execute (with the human correction, if any)
    execution: dict | None  # the executor's result
    verification: dict | None  # did the shop recover? (recovered, checks)
    llm_events: Annotated[list, operator.add]  # LLM failures and fallbacks


TOOLS = {
    fn.__name__: StructuredTool.from_function(
        coroutine=fn, name=fn.__name__, description=fn.__doc__
    )
    for fn in READ_ONLY_TOOLS
}


async def _submit(**_) -> str:
    return "diagnosis received"


SUBMIT_TOOL = StructuredTool.from_function(
    coroutine=_submit,
    name=SUBMIT,
    description="Submit the final diagnosis. Call it only once you have evidence.",
    args_schema=Diagnosis,
)


def build(
    llms: BaseChatModel | list[BaseChatModel],
    checkpointer: BaseCheckpointSaver | None = None,
    *,
    executor: Executor | None = None,
    verifier=None,
    recorder=None,
):
    """`llms`: one model, or several in order of preference (fallback). `executor`,
    `verifier` and `recorder`: who executes the approved action, how it is verified and
    where the incident is recorded (by default, nothing: for tests and dry_run)."""
    executor = executor or NoopExecutor()
    verifier = verifier or NullVerifier()
    recorder = recorder or NullRecorder()
    llms = llms if isinstance(llms, list) else [llms]
    agent_llms = [(model_name(m), m.bind_tools([*TOOLS.values(), SUBMIT_TOOL])) for m in llms]
    diagnosis_llms = [(model_name(m), m.with_structured_output(Diagnosis)) for m in llms]

    async def triage(state: State) -> dict:
        since = state.get("since")
        summary = await overview(datetime.fromisoformat(since).astimezone(UTC) if since else None)
        return {
            "messages": [
                SystemMessage(SYSTEM_PROMPT),
                HumanMessage(
                    f"Alert: {state['alert']}\n\nCurrent state of the system:\n\n{summary}"
                ),
            ],
            "steps": 0,
            "tokens": 0,
        }

    async def agent(state: State) -> dict:
        reply, events = await invoke_with_fallback(agent_llms, state["messages"])
        used = (reply.usage_metadata or {}).get("total_tokens", 0)
        return {"messages": [reply], "tokens": state["tokens"] + used, "llm_events": events}

    async def tools(state: State) -> dict:
        calls = state["messages"][-1].tool_calls

        async def run(call):
            tool = TOOLS.get(call["name"])
            if tool is None:
                result = f"error: no such tool {call['name']}"
            else:
                try:
                    result = await tool.ainvoke(call["args"])
                except Exception as exc:  # invalid arguments: let the agent correct them
                    result = f"error: invalid arguments for {call['name']}: {exc}"
            return ToolMessage(content=result, tool_call_id=call["id"], name=call["name"])

        results = await asyncio.gather(*(run(c) for c in calls))
        contents = fit_to_budget([r.content for r in results], ROUND_BUDGET_CHARS)
        for message, content in zip(results, contents, strict=True):
            message.content = content
        return {"messages": results, "steps": state["steps"] + 1}

    async def finish(state: State) -> dict:
        call = next(c for c in state["messages"][-1].tool_calls if c["name"] == SUBMIT)
        try:
            return {"diagnosis": Diagnosis(**call["args"]).model_dump(), "stop_reason": "submitted"}
        except ValidationError:
            return await force_diagnosis(state)

    async def force_diagnosis(state: State) -> dict:
        messages = state["messages"]
        if isinstance(messages[-1], AIMessage) and messages[-1].tool_calls:
            messages = messages[:-1]  # calls without a response: OpenAI rejects them
        reason = "limit" if _over_limits(state) else "no_submit"
        result, events = await invoke_with_fallback(
            diagnosis_llms,
            [*messages, HumanMessage("Submit the diagnosis now with the evidence you have.")],
        )
        return {"diagnosis": result.model_dump(), "stop_reason": reason, "llm_events": events}

    def route(state: State) -> str:
        reply = state["messages"][-1]
        names = [c["name"] for c in reply.tool_calls]
        if SUBMIT in names:
            return "finish"
        if names and not _over_limits(state):
            return "tools"
        return "force_diagnosis"

    def approval(state: State) -> dict:
        # Pauses here; when resumed with Command(resume=decision), interrupt returns it.
        decision = interrupt({"diagnosis": state["diagnosis"]})
        if not decision["approved"]:
            return {"approval": decision, "approved_action": None}
        proposed = ActionProposal(**state["diagnosis"]["action"])
        override = ActionOverride(**decision["action"]) if decision.get("action") else None
        action = proposed.corrected(override, decision.get("note", ""))
        return {"approval": decision, "approved_action": action.model_dump()}

    async def execute(state: State) -> dict:
        # Only reached with an action approved by a human.
        result = await executor.execute(ActionProposal(**state["approved_action"]))
        return {"execution": result.model_dump()}

    async def verify(state: State) -> dict:
        if state["execution"]["status"] != "executed":
            return {"verification": {"recovered": False, "checks": [], "skipped": True}}
        return {"verification": await verifier.verify()}

    async def record(state: State, config: RunnableConfig) -> dict:
        await recorder.record(config["configurable"]["thread_id"], state)
        return {}

    def after_approval(state: State) -> str:
        return "execute" if state.get("approved_action") else "record"

    graph = StateGraph(State)
    graph.add_node("triage", triage)
    graph.add_node("agent", agent)
    graph.add_node("tools", tools)
    graph.add_node("finish", finish)
    graph.add_node("force_diagnosis", force_diagnosis)
    graph.add_node("approval", approval)
    graph.add_node("execute", execute)
    graph.add_node("verify", verify)
    graph.add_node("record", record)
    graph.add_edge(START, "triage")
    graph.add_edge("triage", "agent")
    graph.add_conditional_edges("agent", route, ["tools", "finish", "force_diagnosis"])
    graph.add_edge("tools", "agent")
    graph.add_edge("finish", "approval")
    graph.add_edge("force_diagnosis", "approval")
    graph.add_conditional_edges("approval", after_approval, ["execute", "record"])
    graph.add_edge("execute", "verify")
    graph.add_edge("verify", "record")
    graph.add_edge("record", END)
    return graph.compile(checkpointer=checkpointer)


def _over_limits(state: State) -> bool:
    return state["steps"] >= MAX_STEPS or state["tokens"] >= MAX_TOKENS
