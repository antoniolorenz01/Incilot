"""Verifica el estado duradero contra el Postgres real, sin LLM (cero tokens).

Con un LLM simulado: arranca una investigación, la corta a mitad, la retoma desde otro
checkpointer (como si fuera otro proceso), comprueba que no repitió pasos, que queda en
pausa esperando aprobación y que la aprobación queda registrada.
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
    return "resumen simulado"


async def _query_metrics(promql: str) -> str:
    """Métricas simuladas."""
    TOOL_CALLS.append(promql)
    return f"resultado de {promql}"


def _check(label: str, ok: bool) -> bool:
    print(f"{'OK   ' if ok else 'FALLA'} {label}", flush=True)
    return ok


async def _run(replies: list, graph_input, thread: dict):
    # Un checkpointer (y una conexión) nuevo en cada etapa: como un proceso distinto.
    async with AsyncPostgresSaver.from_conn_string(config.AGENT_STATE_URL) as checkpointer:
        await checkpointer.setup()
        app = graph.build(FakeLLM(replies=replies), checkpointer)
        with suppress(RuntimeError):  # el corte simulado
            await app.ainvoke(graph_input, thread)
        return await app.aget_state(thread)


async def selftest() -> bool:
    graph.overview = _overview
    graph.TOOLS = {"query_metrics": StructuredTool.from_function(coroutine=_query_metrics)}
    thread = {"configurable": {"thread_id": f"selftest-{uuid4().hex[:8]}"}}

    cut = await _run(
        [call("query_metrics", {"promql": "up"}, "1"), RuntimeError("corte")],
        {"alert": "selftest"},
        thread,
    )
    results = [
        _check("guarda el progreso en Postgres antes del corte", cut.values.get("steps") == 1)
    ]

    resumed = await _run([call("submit_diagnosis", DIAGNOSIS, "2")], None, thread)
    results += [
        _check("retoma sin repetir pasos", TOOL_CALLS == ["up"] and resumed.values["steps"] == 1),
        _check("llega al diagnóstico", resumed.values["diagnosis"]["service"] == "inventory"),
        _check("queda en pausa esperando aprobación", "approval" in resumed.next),
    ]

    decision = {"approved": True, "by": "selftest", "note": ""}
    approved = await _run([], Command(resume=decision), thread)
    results.append(_check("registra la aprobación", approved.values.get("approval") == decision))

    print(f"\n{sum(results)}/{len(results)} OK")
    return all(results)
