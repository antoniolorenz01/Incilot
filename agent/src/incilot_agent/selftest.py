"""Checks durable state against the real Postgres, without an LLM (zero tokens).

With a fake LLM: starts an investigation, cuts it off halfway, resumes it from another
checkpointer (as if it were another process), and checks that it did not repeat steps,
that it pauses awaiting approval and that the approval is recorded.
"""

from contextlib import suppress
from uuid import uuid4

from langchain_core.tools import StructuredTool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command

from incilot_agent import config, graph
from incilot_agent.testing import DIAGNOSIS, FakeLLM, call

TOOL_CALLS: list[str] = []


async def _overview() -> str:
    return "simulated overview"


async def _query_metrics(promql: str) -> str:
    """Simulated metrics."""
    TOOL_CALLS.append(promql)
    return f"result of {promql}"


def _check(label: str, ok: bool) -> bool:
    print(f"{'OK   ' if ok else 'FAIL '} {label}", flush=True)
    return ok


async def _run(replies: list, graph_input, thread: dict):
    # A new checkpointer (and connection) at each stage: like a separate process.
    async with AsyncPostgresSaver.from_conn_string(config.AGENT_STATE_URL) as checkpointer:
        await checkpointer.setup()
        app = graph.build(FakeLLM(replies=replies), checkpointer)
        with suppress(RuntimeError):  # the simulated outage
            await app.ainvoke(graph_input, thread)
        return await app.aget_state(thread)


async def selftest() -> bool:
    graph.overview = _overview
    graph.TOOLS = {"query_metrics": StructuredTool.from_function(coroutine=_query_metrics)}
    thread = {"configurable": {"thread_id": f"selftest-{uuid4().hex[:8]}"}}

    cut = await _run(
        [call("query_metrics", {"promql": "up"}, "1"), RuntimeError("outage")],
        {"alert": "selftest"},
        thread,
    )
    results = [_check("saves progress to Postgres before the outage", cut.values.get("steps") == 1)]

    resumed = await _run([call("submit_diagnosis", DIAGNOSIS, "2")], None, thread)
    results += [
        _check(
            "resumes without repeating steps", TOOL_CALLS == ["up"] and resumed.values["steps"] == 1
        ),
        _check("reaches the diagnosis", resumed.values["diagnosis"]["service"] == "inventory"),
        _check("pauses awaiting approval", "approval" in resumed.next),
    ]

    decision = {"approved": True, "by": "selftest", "note": ""}
    approved = await _run([], Command(resume=decision), thread)
    results.append(_check("records the approval", approved.values.get("approval") == decision))

    print(f"\n{sum(results)}/{len(results)} OK")
    return all(results)
