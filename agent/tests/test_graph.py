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
        return "all quiet"

    async def query_metrics(promql: str) -> str:
        """Fake metrics."""
        TOOL_CALLS.append(promql)
        return f"result of {promql}"

    monkeypatch.setattr(graph, "overview", overview)
    monkeypatch.setattr(
        graph, "TOOLS", {"query_metrics": StructuredTool.from_function(coroutine=query_metrics)}
    )


THREAD = {"configurable": {"thread_id": "t1"}}


NEW = {"alert": "test"}


def investigate(*replies, checkpointer=None, graph_input=NEW):
    """graph_input=None resumes the thread's investigation from its last checkpoint."""
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
    assert state["messages"][3].content == "result of up"


def test_step_limit_forces_a_diagnosis(monkeypatch):
    monkeypatch.setattr(graph, "MAX_STEPS", 1)
    state = investigate(
        call("query_metrics", {"promql": "up"}, "1"),
        call("query_metrics", {"promql": "other"}, "2"),
    )
    assert state["stop_reason"] == "limit"
    assert state["diagnosis"]["service"] == "forced"


def test_invalid_arguments_are_reported_to_the_agent():
    state = investigate(
        call("query_metrics", {"wrong": 1}, "1"),
        call("submit_diagnosis", DIAGNOSIS, "2"),
    )
    assert state["messages"][3].content.startswith("error: invalid arguments")


def test_malformed_submission_falls_back_to_forced_diagnosis():
    state = investigate(call("submit_diagnosis", {"service": "x"}, "1"))
    assert state["diagnosis"]["service"] == "forced"


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
            RuntimeError("the process died"),
            checkpointer=checkpointer,
        )
    assert TOOL_CALLS == ["up"]

    resumed = investigate(
        call("submit_diagnosis", DIAGNOSIS, "2"), checkpointer=checkpointer, graph_input=None
    )
    assert TOOL_CALLS == ["up"]  # the tool was not run again
    assert resumed["steps"] == 1
    assert resumed["diagnosis"]["service"] == "inventory"


def test_falls_back_to_the_next_model_and_records_it():
    primary = FakeLLM(replies=[ConnectionError("503 from the provider")])
    backup = FakeLLM(replies=[call("submit_diagnosis", DIAGNOSIS, "1")])
    app = graph.build([primary, backup], InMemorySaver())
    state = asyncio.run(app.ainvoke({"alert": "test"}, THREAD))

    assert state["diagnosis"]["service"] == "inventory"
    [event] = state["llm_events"]
    assert event["error"].startswith("ConnectionError: 503")
    assert event["fallback_to"] == "FakeLLM"


def test_when_every_model_fails_the_investigation_stops_and_can_resume():
    checkpointer = InMemorySaver()
    failing = [FakeLLM(replies=[ConnectionError("down")]) for _ in range(2)]
    with pytest.raises(ConnectionError):
        asyncio.run(graph.build(failing, checkpointer).ainvoke({"alert": "test"}, THREAD))

    recovered = FakeLLM(replies=[call("submit_diagnosis", DIAGNOSIS, "1")])
    state = asyncio.run(graph.build(recovered, checkpointer).ainvoke(None, THREAD))
    assert state["diagnosis"]["service"] == "inventory"


def test_investigation_events_sequence():
    from incilot_agent.events import investigation_events

    async def collect(app, graph_input):
        return [e["type"] async for e in investigation_events(app, graph_input, THREAD)]

    checkpointer = InMemorySaver()
    llm = FakeLLM(
        replies=[
            call("query_metrics", {"promql": "up"}, "1"),
            call("submit_diagnosis", DIAGNOSIS, "2"),
        ]
    )
    app = graph.build(llm, checkpointer)
    assert asyncio.run(collect(app, {"alert": "test"})) == [
        "triage",
        "tool_call",
        "tool_result",
        "diagnosis",
        "awaiting_approval",
    ]
    decision = Command(resume={"approved": True, "by": "toni", "note": ""})
    assert asyncio.run(collect(app, decision)) == ["approval", "execution", "verification", "done"]


def test_human_can_correct_the_action_when_approving():
    checkpointer = InMemorySaver()
    investigate(call("submit_diagnosis", DIAGNOSIS, "1"), checkpointer=checkpointer)
    decision = {
        "approved": True,
        "by": "toni",
        "note": "it was another commit",
        "action": {"target": "def5678"},
    }
    done = investigate(checkpointer=checkpointer, graph_input=Command(resume=decision))
    action = done["approved_action"]
    assert action["kind"] == "rollback" and action["target"] == "def5678"
    assert "corrected by a human: it was another commit" in action["reason"]


def test_rejected_investigation_has_no_action_to_execute():
    checkpointer = InMemorySaver()
    investigate(call("submit_diagnosis", DIAGNOSIS, "1"), checkpointer=checkpointer)
    decision = {"approved": False, "by": "toni", "note": "no"}
    done = investigate(checkpointer=checkpointer, graph_input=Command(resume=decision))
    assert done["approved_action"] is None


class RecordingExecutor:
    name = "fake"

    def __init__(self):
        self.actions = []

    async def execute(self, action):
        from incilot_agent.executor import ExecutionResult

        self.actions.append(action)
        return ExecutionResult(status="executed", detail="ok", connector=self.name)


def test_approved_action_is_executed_and_rejected_is_not():
    from incilot_agent import graph as g

    for approved, expected_calls in ((True, 1), (False, 0)):
        executor, checkpointer = RecordingExecutor(), InMemorySaver()
        llm = FakeLLM(replies=[call("submit_diagnosis", DIAGNOSIS, "1")])
        app = g.build(llm, checkpointer, executor=executor)
        asyncio.run(app.ainvoke({"alert": "test"}, THREAD))
        assert executor.actions == []  # nothing runs before approval

        decision = {"approved": approved, "by": "toni", "note": "", "action": {"target": "def5678"}}
        done = asyncio.run(app.ainvoke(Command(resume=decision), THREAD))
        assert len(executor.actions) == expected_calls
        if approved:
            assert executor.actions[0].target == "def5678"
            assert done["execution"]["status"] == "executed"


class FakeVerifier:
    async def verify(self):
        return {"recovered": True, "checks": [{"name": "x", "value": 0, "max": 1, "ok": True}]}


class FakeRecorder:
    def __init__(self):
        self.records = {}

    async def record(self, incident_id, state):
        self.records[incident_id] = state


def test_executed_action_is_verified_and_the_incident_recorded():
    recorder, checkpointer = FakeRecorder(), InMemorySaver()
    llm = FakeLLM(replies=[call("submit_diagnosis", DIAGNOSIS, "1")])
    app = graph.build(
        llm, checkpointer, executor=RecordingExecutor(), verifier=FakeVerifier(), recorder=recorder
    )
    asyncio.run(app.ainvoke({"alert": "test"}, THREAD))
    decision = {"approved": True, "by": "toni", "note": ""}
    done = asyncio.run(app.ainvoke(Command(resume=decision), THREAD))

    assert done["verification"]["recovered"] is True
    recorded = recorder.records["t1"]
    assert recorded["diagnosis"]["service"] == "inventory"
    assert recorded["approval"]["by"] == "toni"
    assert recorded["execution"]["status"] == "executed"


def test_rejected_incident_is_recorded_without_execution():
    recorder, checkpointer = FakeRecorder(), InMemorySaver()
    llm = FakeLLM(replies=[call("submit_diagnosis", DIAGNOSIS, "1")])
    app = graph.build(llm, checkpointer, executor=RecordingExecutor(), recorder=recorder)
    asyncio.run(app.ainvoke({"alert": "test"}, THREAD))
    decision = {"approved": False, "by": "toni", "note": "no"}
    asyncio.run(app.ainvoke(Command(resume=decision), THREAD))
    assert recorder.records["t1"]["approval"]["approved"] is False
    assert recorder.records["t1"].get("execution") is None
