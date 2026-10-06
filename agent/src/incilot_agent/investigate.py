"""Investigaciones del agente, con el estado guardado en Postgres (agent_state).

python -m incilot_agent.investigate ["descripción de la alerta"]   # nueva
python -m incilot_agent.investigate --resume ID     # retoma desde el último paso
python -m incilot_agent.investigate --approve ID    # aprueba la acción propuesta
python -m incilot_agent.investigate --reject ID     # la rechaza
python -m incilot_agent.investigate --check-tools   # prueba cada herramienta una vez
python -m incilot_agent.investigate --selftest      # estado duradero, sin LLM
"""

import argparse
import asyncio
import json
import os
from uuid import uuid4

from langchain_openai import ChatOpenAI
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command

from incilot_agent import config, graph
from incilot_agent.selftest import selftest
from incilot_agent.tools import READ_ONLY_TOOLS

DEFAULT_ALERT = "Se reportó una degradación en la tienda: hay quejas de clientes."
CHECKS = {
    "query_metrics": {"promql": "sum by (service) (rate(http_requests_total[1m]))", "minutes": 5},
    "search_logs": {"level": "error", "minutes": 10, "limit": 3},
    "list_commits": {"since_minutes": 60 * 24 * 7, "limit": 3},
    "show_commit": {"sha": "HEAD"},
    "read_file": {"path": "config/shop.env"},
    "search_runbooks": {"query": "latencia", "limit": 1},
    "query_database": {"database": "inventory", "sql": "SELECT count(*) FROM pg_stat_activity"},
}


def short(text: str, lines: int = 3) -> str:
    rows = text.splitlines()
    more = f"\n      … ({len(rows) - lines} líneas más)" if len(rows) > lines else ""
    return "\n".join(f"      {r[:160]}" for r in rows[:lines]) + more


async def check_tools() -> bool:
    ok = True
    for tool in READ_ONLY_TOOLS:
        result = await tool(**CHECKS[tool.__name__])
        failed = result.startswith("error:")
        ok &= not failed
        print(f"{'FALLA' if failed else 'OK   '} {tool.__name__:16} {result.splitlines()[0][:100]}")
    return ok


async def run(graph_input, thread_id: str) -> None:
    llm = ChatOpenAI(model=os.environ["OPENAI_MODEL"], timeout=60, max_retries=2)
    run_config = {"configurable": {"thread_id": thread_id}}
    async with AsyncPostgresSaver.from_conn_string(config.AGENT_STATE_URL) as checkpointer:
        await checkpointer.setup()
        app = graph.build(llm, checkpointer)
        steps = (await app.aget_state(run_config)).values.get("steps", 0)

        async for update in app.astream(graph_input, run_config, stream_mode="updates"):
            for node, change in update.items():
                if node == "__interrupt__":
                    continue
                if node == "triage":
                    print("[triage] resumen del sistema listo")
                elif node == "agent":
                    for call in change["messages"][-1].tool_calls:
                        args = json.dumps(call["args"], ensure_ascii=False)
                        print(f"\n[ronda {steps + 1}] {call['name']}({args[:200]})")
                elif node == "tools":
                    steps = change["steps"]
                    for message in change["messages"]:
                        print(short(message.content))

        snapshot = await app.aget_state(run_config)
    state = snapshot.values
    if not state:
        print(f"no existe la investigación {thread_id}")
        return
    print(f"\n=== Diagnóstico ({state.get('stop_reason')}, {state.get('tokens', 0)} tokens) ===")
    print(json.dumps(state.get("diagnosis"), indent=2, ensure_ascii=False))
    if "approval" in snapshot.next:
        print("\nEsperando aprobación de la acción propuesta. Para decidir:")
        print(f'  make investigate ARGS="--approve {thread_id}"   (o --reject)')
    elif state.get("approval"):
        verdict = "APROBADA" if state["approval"]["approved"] else "RECHAZADA"
        print(f"\nAcción {verdict} por {state['approval']['by']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Investigaciones de IncidentPilot")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--resume", metavar="ID")
    group.add_argument("--approve", metavar="ID")
    group.add_argument("--reject", metavar="ID")
    group.add_argument("--check-tools", action="store_true")
    group.add_argument("--selftest", action="store_true")
    parser.add_argument("alert", nargs="*", help="descripción de la alerta")
    args = parser.parse_args()

    if args.check_tools:
        raise SystemExit(0 if asyncio.run(check_tools()) else 1)
    if args.selftest:
        raise SystemExit(0 if asyncio.run(selftest()) else 1)
    if args.resume:
        print(f"Retomando la investigación {args.resume}")
        asyncio.run(run(None, args.resume))
    elif args.approve or args.reject:
        decision = {"approved": bool(args.approve), "by": os.getenv("USER", "guardia"), "note": ""}
        asyncio.run(run(Command(resume=decision), args.approve or args.reject))
    else:
        thread_id = uuid4().hex[:12]
        alert = " ".join(args.alert) or DEFAULT_ALERT
        print(f"Investigación {thread_id} (si se corta: --resume {thread_id})")
        print(f"Alerta: {alert}\nModelo: {os.environ['OPENAI_MODEL']}\n")
        asyncio.run(run({"alert": alert}, thread_id))


if __name__ == "__main__":
    main()
