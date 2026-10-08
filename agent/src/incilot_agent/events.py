"""An investigation's steps as events: the same source for the console and the API.

Event types:
    triage            initial overview ready
    tool_call         the agent requests a tool (name, args, round)
    tool_result       a tool's result (name, content)
    llm_fallback      a model failed and the next one took over (model, error, fallback_to)
    diagnosis         structured diagnosis (diagnosis, stop_reason, tokens)
    awaiting_approval the investigation paused awaiting human approval
    approval          decision recorded (approved, by, note, action)
    execution         result of executing the approved action (status, detail, connector)
    verification      did the shop recover? (recovered, checks)
    done              the investigation finished
"""

from collections.abc import AsyncIterator

from incilot_agent.graph import SUBMIT

TERMINAL = {"done", "error"}


async def investigation_events(app, graph_input, config: dict) -> AsyncIterator[dict]:
    """Runs (or resumes) the investigation and emits its events as it goes."""
    rounds = (await app.aget_state(config)).values.get("steps", 0)

    async for update in app.astream(graph_input, config, stream_mode="updates"):
        for node, change in update.items():
            if node in ("__interrupt__", "record") or not change:
                continue
            for event in change.get("llm_events", []):
                yield {"type": "llm_fallback", **event}
            if node == "triage":
                yield {"type": "triage"}
            elif node == "agent":
                for call in change["messages"][-1].tool_calls:
                    if call["name"] == SUBMIT:
                        continue  # covered by the `diagnosis` event
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
            elif node == "execute":
                yield {"type": "execution", **change["execution"]}
            elif node == "verify":
                yield {"type": "verification", **change["verification"]}

    snapshot = await app.aget_state(config)
    if "approval" in snapshot.next:
        yield {"type": "awaiting_approval"}
    elif snapshot.values:
        yield {"type": "done"}
