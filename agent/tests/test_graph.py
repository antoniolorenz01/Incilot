import asyncio

import pytest
from langchain_core.tools import StructuredTool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from incilot_agent import graph
from incilot_agent.testing import DIAGNOSIS, FakeLLM, call

TOOL_CALLS = []


@pytest.fixture(autouse=True)
def fake_sources(monkeypatch):
    TOOL_CALLS.clear()

    async def overview():
        return "todo tranquilo"

    async def query_metrics(promql: str) -> str:
        """Métricas falsas."""
        TOOL_CALLS.append(promql)
        return f"resultado de {promql}"

    monkeypatch.setattr(graph, "overview", overview)
    monkeypatch.setattr(
        graph, "TOOLS", {"query_metrics": StructuredTool.from_function(coroutine=query_metrics)}
    )


THREAD = {"configurable": {"thread_id": "t1"}}


NEW = {"alert": "test"}


def investigate(*replies, checkpointer=None, graph_input=NEW):
    """graph_input=None retoma la investigación del thread desde su último checkpoint."""
    app = graph.build(FakeLLM(replies=list(replies)), checkpointer or InMemorySaver())
    return asyncio.run(app.ainvoke(graph_input, THREAD))


def test_tools_then_submitted_diagnosis():
    state = investigate(
        call("query_metrics", {"promql": "up"}, "1"),
        call("submit_diagnosis", DIAGNOSIS, "2"),
    )
    assert state["stop_reason"] == "submitted"
    assert state["diagnosis"]["service"] == "inventory"
    assert state["steps"] == 1
    assert state["messages"][3].content == "resultado de up"


def test_step_limit_forces_a_diagnosis(monkeypatch):
    monkeypatch.setattr(graph, "MAX_STEPS", 1)
    state = investigate(
        call("query_metrics", {"promql": "up"}, "1"),
        call("query_metrics", {"promql": "otra"}, "2"),
    )
    assert state["stop_reason"] == "limit"
    assert state["diagnosis"]["service"] == "forzado"


def test_invalid_arguments_are_reported_to_the_agent():
    state = investigate(
        call("query_metrics", {"wrong": 1}, "1"),
        call("submit_diagnosis", DIAGNOSIS, "2"),
    )
    assert state["messages"][3].content.startswith("error: argumentos inválidos")


def test_malformed_submission_falls_back_to_forced_diagnosis():
    state = investigate(call("submit_diagnosis", {"service": "x"}, "1"))
    assert state["diagnosis"]["service"] == "forzado"


def test_diagnosis_pauses_for_approval_and_records_the_decision():
    checkpointer = InMemorySaver()
    paused = investigate(call("submit_diagnosis", DIAGNOSIS, "1"), checkpointer=checkpointer)
    assert paused["__interrupt__"][0].value["diagnosis"]["service"] == "inventory"
    assert paused.get("approval") is None

    decision = {"approved": True, "by": "toni", "note": ""}
    done = investigate(checkpointer=checkpointer, graph_input=Command(resume=decision))
    assert done["approval"] == decision


def test_rejection_is_recorded():
    checkpointer = InMemorySaver()
    investigate(call("submit_diagnosis", DIAGNOSIS, "1"), checkpointer=checkpointer)
    decision = {"approved": False, "by": "toni", "note": "no"}
    done = investigate(checkpointer=checkpointer, graph_input=Command(resume=decision))
    assert done["approval"]["approved"] is False


def test_interrupted_investigation_resumes_without_repeating_steps():
    checkpointer = InMemorySaver()
    with pytest.raises(RuntimeError):
        investigate(
            call("query_metrics", {"promql": "up"}, "1"),
            RuntimeError("se cortó el proceso"),
            checkpointer=checkpointer,
        )
    assert TOOL_CALLS == ["up"]

    resumed = investigate(
        call("submit_diagnosis", DIAGNOSIS, "2"), checkpointer=checkpointer, graph_input=None
    )
    assert TOOL_CALLS == ["up"]  # la herramienta no se volvió a ejecutar
    assert resumed["steps"] == 1
    assert resumed["diagnosis"]["service"] == "inventory"


def test_falls_back_to_the_next_model_and_records_it():
    primary = FakeLLM(replies=[ConnectionError("503 del proveedor")])
    backup = FakeLLM(replies=[call("submit_diagnosis", DIAGNOSIS, "1")])
    app = graph.build([primary, backup], InMemorySaver())
    state = asyncio.run(app.ainvoke({"alert": "test"}, THREAD))

    assert state["diagnosis"]["service"] == "inventory"
    [event] = state["llm_events"]
    assert event["error"].startswith("ConnectionError: 503")
    assert event["fallback_to"] == "FakeLLM"


def test_when_every_model_fails_the_investigation_stops_and_can_resume():
    checkpointer = InMemorySaver()
    failing = [FakeLLM(replies=[ConnectionError("caído")]) for _ in range(2)]
    with pytest.raises(ConnectionError):
        asyncio.run(graph.build(failing, checkpointer).ainvoke({"alert": "test"}, THREAD))

    recovered = FakeLLM(replies=[call("submit_diagnosis", DIAGNOSIS, "1")])
    state = asyncio.run(graph.build(recovered, checkpointer).ainvoke(None, THREAD))
    assert state["diagnosis"]["service"] == "inventory"
