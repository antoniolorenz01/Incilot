"""El grafo de investigación.

    triage ──► agent ⇄ tools ──► finish ───────────┐
                 └──────────────► force_diagnosis ─┴──► approval (pausa)
                                  (límite de pasos o de tokens)

- triage: resumen del sistema sin LLM (triage.py).
- agent: el LLM decide qué herramienta usar o, cuando tiene la causa raíz con
  evidencia, llama a `submit_diagnosis`.
- tools: ejecuta las herramientas de solo lectura y devuelve los resultados.
- finish / force_diagnosis: dejan el diagnóstico estructurado en el estado.
- approval: pausa el grafo (interrupt) hasta que un humano apruebe o rechace la
  acción propuesta. El estado queda en el checkpointer: se retoma desde otro proceso.

Con un checkpointer (Postgres en producción) cada paso queda guardado: una
investigación cortada a mitad se retoma desde el último paso completo.
"""

import asyncio
import operator
import os
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
MAX_TOKENS = int(os.getenv("AGENT_MAX_TOKENS", "150000"))
# Tope de lo que devuelven las herramientas en una ronda (~4 caracteres por token).
ROUND_BUDGET_CHARS = int(os.getenv("AGENT_ROUND_BUDGET_CHARS", "16000"))
SUBMIT = "submit_diagnosis"

SYSTEM_PROMPT = """\
Sos el ingeniero de guardia (SRE) de una tienda online. Hay un incidente en curso y
tenés que encontrar la causa raíz con evidencia y proponer una acción para resolverlo.

La tienda tiene 4 servicios: shop (la entrada: orquesta los pedidos llamando a users,
inventory y payments), users, inventory y payments; usan Postgres y Redis. Cada merge
a main del repo de la empresa se despliega automáticamente.

Cómo investigar:
1. Ubicá el origen, no solo el síntoma: si una dependencia falla, el que se queja es
   shop (timeouts, 502). Seguí la cadena hasta el servicio o componente que falla.
2. Formulá hipótesis y verificalas con evidencia: métricas, logs, commits, config y la
   base de datos (pg_stat_activity y pg_locks para sesiones y bloqueos). Con
   search_knowledge encontrás runbooks, docs y el código relevante por tema.
3. Revisá los cambios recientes, pero no asumas que el último commit es el culpable:
   relacioná el contenido del cambio con el síntoma y con el momento en que empezó.
4. Hay ruido de fondo: errores transitorios sueltos y picos aislados pasan siempre y no
   son el incidente. Buscá lo que cambió de forma sostenida. El triage inicial ya compara
   cada métrica con su línea base y marca los errores de los logs como NUEVO, CRECIÓ o
   estable: los estables existían antes del incidente y no lo explican. Si la alerta dice desde
   cuándo, concentrate en lo que empezó o cambió a partir de ese momento: lo anterior
   puede ser de otro incidente ya resuelto.
5. La causa puede ser externa (un proveedor) o de infraestructura, sin commit culpable.

Usá solo datos que obtuviste con las herramientas; no inventes. Cuando tengas la causa
raíz con evidencia, terminá llamando a submit_diagnosis."""


class State(TypedDict):
    alert: str
    messages: Annotated[list, add_messages]
    steps: int
    tokens: int
    diagnosis: dict | None
    stop_reason: str | None
    approval: dict | None  # {"approved": bool, "by": str, "note": str, "action": override}
    approved_action: dict | None  # la acción a ejecutar (con la corrección humana, si hubo)
    execution: dict | None  # resultado del ejecutor
    verification: dict | None  # ¿se recuperó la tienda? (recovered, checks)
    llm_events: Annotated[list, operator.add]  # fallos del LLM y caídas al respaldo


TOOLS = {
    fn.__name__: StructuredTool.from_function(
        coroutine=fn, name=fn.__name__, description=fn.__doc__
    )
    for fn in READ_ONLY_TOOLS
}


async def _submit(**_) -> str:
    return "diagnóstico recibido"


SUBMIT_TOOL = StructuredTool.from_function(
    coroutine=_submit,
    name=SUBMIT,
    description="Entrega el diagnóstico final. Llamala solo cuando tengas evidencia.",
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
    """`llms`: un modelo, o varios en orden de preferencia (fallback). `executor`,
    `verifier` y `recorder`: quién ejecuta la acción aprobada, cómo se verifica y dónde se
    registra el incidente (por defecto, nada: para tests y dry_run)."""
    executor = executor or NoopExecutor()
    verifier = verifier or NullVerifier()
    recorder = recorder or NullRecorder()
    llms = llms if isinstance(llms, list) else [llms]
    agent_llms = [(model_name(m), m.bind_tools([*TOOLS.values(), SUBMIT_TOOL])) for m in llms]
    diagnosis_llms = [(model_name(m), m.with_structured_output(Diagnosis)) for m in llms]

    async def triage(state: State) -> dict:
        summary = await overview()
        return {
            "messages": [
                SystemMessage(SYSTEM_PROMPT),
                HumanMessage(
                    f"Alerta: {state['alert']}\n\nEstado actual del sistema:\n\n{summary}"
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
                result = f"error: no existe la herramienta {call['name']}"
            else:
                try:
                    result = await tool.ainvoke(call["args"])
                except Exception as exc:  # argumentos inválidos: que el agente corrija
                    result = f"error: argumentos inválidos para {call['name']}: {exc}"
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
            messages = messages[:-1]  # llamadas sin respuesta: OpenAI no las acepta
        reason = "limit" if _over_limits(state) else "no_submit"
        result, events = await invoke_with_fallback(
            diagnosis_llms,
            [*messages, HumanMessage("Entregá ahora el diagnóstico con la evidencia que tenés.")],
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
        # Se pausa acá; al retomar con Command(resume=decisión), interrupt la devuelve.
        decision = interrupt({"diagnosis": state["diagnosis"]})
        if not decision["approved"]:
            return {"approval": decision, "approved_action": None}
        proposed = ActionProposal(**state["diagnosis"]["action"])
        override = ActionOverride(**decision["action"]) if decision.get("action") else None
        action = proposed.corrected(override, decision.get("note", ""))
        return {"approval": decision, "approved_action": action.model_dump()}

    async def execute(state: State) -> dict:
        # Solo se llega acá con una acción aprobada por un humano.
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
