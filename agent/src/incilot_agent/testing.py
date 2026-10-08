"""Pieces for testing the graph without a real LLM (tests and --selftest)."""

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import RunnableLambda

DIAGNOSIS = {
    "service": "inventory",
    "root_cause": "slow query after the deploy",
    "culprit_commit": "abc1234",
    "evidence": ["inventory p95 at 950 ms"],
    "confidence": "high",
    "plan": ["revert the commit", "verify that the inventory p95 returns to normal"],
    "action": {
        "kind": "rollback",
        "target": "abc1234",
        "reason": "revert the query",
        "evidence": ["the commit adds a subselect per product"],
    },
}


class FakeLLM(BaseChatModel):
    """Returns fixed replies in order. An exception in the list is raised (simulates an
    outage). with_structured_output returns DIAGNOSIS with service="forced"."""

    replies: list

    @property
    def _llm_type(self) -> str:
        return "fake"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return ChatResult(generations=[ChatGeneration(message=reply)])

    def bind_tools(self, tools, **kwargs):
        return self

    def with_structured_output(self, schema, **kwargs):
        return RunnableLambda(lambda _: schema(**(DIAGNOSIS | {"service": "forced"})))


def call(name: str, args: dict, id_: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": id_}])
