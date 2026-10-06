"""Piezas para probar el grafo sin un LLM real (tests y --selftest)."""

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import RunnableLambda

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
    """Devuelve respuestas fijas en orden. Una excepción en la lista se lanza (simula un
    corte). with_structured_output devuelve DIAGNOSIS con service="forzado"."""

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
        return RunnableLambda(lambda _: schema(**(DIAGNOSIS | {"service": "forzado"})))


def call(name: str, args: dict, id_: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": id_}])
