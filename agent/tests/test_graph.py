import asyncio

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import RunnableLambda
from langchain_core.tools import StructuredTool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from incilot_agent import graph

DIAGNOSIS = {
    "service": "inventory",
    "root_cause": "consulta lenta tras el deploy",
    "culprit_commit": "abc1234",
    "evidence": ["p95 de inventory a 950 ms"],
    "confidence": "high",
    "action": {
        "kind": "rollback",
        "target": "abc1234",
        "reason": "revertir la consulta",
        "evidence": ["el commit agrega un subselect por producto"],
    },
}


class FakeLLM(BaseChatModel):
    """Devuelve respuestas fijas; with_structured_output devuelve DIAGNOSIS con otro servicio."""

    replies: list

    @property
    def _llm_type(self) -> str:
        return "fake"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):  # simula que el proceso se corta acá
            raise reply
        return ChatResult(generations=[ChatGeneration(message=reply)])

    def bind_tools(self, tools, **kwargs):
        return self

    def with_structured_output(self, schema, **kwargs):
        return RunnableLambda(lambda _: schema(**(DIAGNOSIS | {"service": "forzado"})))


def call(name, args, id_):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": id_}])


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
