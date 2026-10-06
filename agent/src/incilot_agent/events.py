"""Los pasos de una investigación como eventos: la misma fuente para la consola y la API.

Tipos de evento:
    triage            resumen inicial listo
    tool_call         el agente pide una herramienta (name, args, round)
    tool_result       resultado de una herramienta (name, content)
    llm_fallback      un modelo falló y se pasó al siguiente (model, error, fallback_to)
    diagnosis         diagnóstico estructurado (diagnosis, stop_reason, tokens)
    awaiting_approval la investigación se pausó esperando aprobación humana
    approval          decisión registrada (approved, by, note)
    done              la investigación terminó
"""

from collections.abc import AsyncIterator

from incilot_agent.graph import SUBMIT

TERMINAL = {"done", "error"}


async def investigation_events(app, graph_input, config: dict) -> AsyncIterator[dict]:
    """Corre (o retoma) la investigación y va emitiendo sus eventos."""
    rounds = (await app.aget_state(config)).values.get("steps", 0)

    async for update in app.astream(graph_input, config, stream_mode="updates"):
        for node, change in update.items():
            if node == "__interrupt__" or not change:
                continue
            for event in change.get("llm_events", []):
                yield {"type": "llm_fallback", **event}
            if node == "triage":
                yield {"type": "triage"}
            elif node == "agent":
                for call in change["messages"][-1].tool_calls:
                    if call["name"] == SUBMIT:
                        continue  # lo cubre el evento `diagnosis`
                    yield {
                        "type": "tool_call",
                        "name": call["name"],
                        "args": call["args"],
                        "round": rounds + 1,
                    }
            elif node == "tools":
                rounds = change["steps"]
                for message in change["messages"]:
                    yield {"type": "tool_result", "name": message.name, "content": message.content}
            elif node in ("finish", "force_diagnosis"):
                state = (await app.aget_state(config)).values
                yield {
                    "type": "diagnosis",
                    "diagnosis": change["diagnosis"],
                    "stop_reason": change["stop_reason"],
                    "tokens": state.get("tokens", 0),
                }
            elif node == "approval":
                yield {"type": "approval", **change["approval"]}

    snapshot = await app.aget_state(config)
    if "approval" in snapshot.next:
        yield {"type": "awaiting_approval"}
    elif snapshot.values:
        yield {"type": "done"}
