"""Investigaciones del agente, con el estado guardado en Postgres (agent_state).

python -m incilot_agent.investigate ["descripción de la alerta"]   # nueva
python -m incilot_agent.investigate --resume ID     # retoma desde el último paso
python -m incilot_agent.investigate --approve ID    # aprueba la acción propuesta
python -m incilot_agent.investigate --approve ID --target SHA [--kind K] [--note N]
                                                   # aprueba corrigiendo la acción
python -m incilot_agent.investigate --reject ID     # la rechaza
python -m incilot_agent.investigate --check-tools   # prueba cada herramienta una vez
python -m incilot_agent.investigate --selftest      # estado duradero, sin LLM
"""

import argparse
import asyncio
import json
import os
from uuid import uuid4

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command

from incilot_agent import config, graph
from incilot_agent.events import investigation_events
from incilot_agent.executor import default_executor
from incilot_agent.llm import openai_models
from incilot_agent.selftest import selftest
from incilot_agent.tools import READ_ONLY_TOOLS
from incilot_agent.verification import PostgresRecorder, PrometheusVerifier

DEFAULT_ALERT = "Se reportó una degradación en la tienda: hay quejas de clientes."
CHECKS = {
    "query_metrics": {"promql": "sum by (service) (rate(http_requests_total[1m]))", "minutes": 5},
    "search_logs": {"level": "error", "minutes": 10, "limit": 3},
    "list_commits": {"since_minutes": 60 * 24 * 7, "limit": 3},
    "show_commit": {"sha": "HEAD"},
    "read_file": {"path": "config/shop.env"},
    "search_knowledge": {"query": "latencia alta en inventory", "limit": 1},
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


def render(event: dict) -> str | None:
    """Una línea de consola por evento (None: no se muestra)."""
    match event["type"]:
        case "triage":
            return "[triage] resumen del sistema listo"
        case "tool_call":
            args = json.dumps(event["args"], ensure_ascii=False)
            return f"\n[ronda {event['round']}] {event['name']}({args[:200]})"
        case "tool_result":
            return short(event["content"])
        case "llm_fallback":
            target = event["fallback_to"] or "sin respaldo"
            return f"\n[llm] {event['model']} falló ({event['error'][:80]}) → {target}"
        case "diagnosis":
            header = f"\n=== Diagnóstico ({event['stop_reason']}, {event['tokens']} tokens) ==="
            return header + "\n" + json.dumps(event["diagnosis"], indent=2, ensure_ascii=False)
        case "approval":
            verdict = "APROBADA" if event["approved"] else "RECHAZADA"
            return f"\nAcción {verdict} por {event['by']}"
        case "execution":
            return f"[ejecución] {event['status']} ({event['connector']}): {event['detail']}"
        case "verification":
            if event.get("skipped"):
                return "[verificación] no se verificó: la acción no se ejecutó"
            lines = [
                f"  {'OK' if c['ok'] else '✗ '} {c['name']}: {c['value']} (máx {c['max']})"
                for c in event["checks"]
            ]
            verdict = "RESUELTO" if event["recovered"] else "SIGUE EL PROBLEMA"
            return f"[verificación] {verdict}\n" + "\n".join(lines)
    return None


async def run(graph_input, thread_id: str) -> None:
    run_config = {"configurable": {"thread_id": thread_id}}
    async with AsyncPostgresSaver.from_conn_string(config.AGENT_STATE_URL) as checkpointer:
        await checkpointer.setup()
        app = graph.build(
            openai_models(),
            checkpointer,
            executor=default_executor(),
            verifier=PrometheusVerifier(),
            recorder=PostgresRecorder(),
        )
        if graph_input is None and not (await app.aget_state(run_config)).values:
            print(f"no existe la investigación {thread_id}")
            return
        async for event in investigation_events(app, graph_input, run_config):
            if line := render(event):
                print(line)
            if event["type"] == "awaiting_approval":
                print("\nEsperando aprobación de la acción propuesta. Para decidir:")
                print(f'  make investigate ARGS="--approve {thread_id}"   (o --reject)')


def main() -> None:
    parser = argparse.ArgumentParser(description="Investigaciones de IncidentPilot")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--resume", metavar="ID")
    group.add_argument("--approve", metavar="ID")
    group.add_argument("--reject", metavar="ID")
    group.add_argument("--check-tools", action="store_true")
    group.add_argument("--selftest", action="store_true")
    parser.add_argument("--kind", help="al aprobar: corregir el tipo de acción")
    parser.add_argument("--target", help="al aprobar: corregir el objetivo (commit, servicio…)")
    parser.add_argument("--note", default="", help="al aprobar o rechazar: comentario")
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
        override = {k: v for k, v in {"kind": args.kind, "target": args.target}.items() if v}
        decision = {
            "approved": bool(args.approve),
            "by": os.getenv("USER", "guardia"),
            "note": args.note,
            "action": override or None,
        }
        asyncio.run(run(Command(resume=decision), args.approve or args.reject))
    else:
        thread_id = uuid4().hex[:12]
        alert = " ".join(args.alert) or DEFAULT_ALERT
        print(f"Investigación {thread_id} (si se corta: --resume {thread_id})")
        fallback = os.getenv("OPENAI_FALLBACK_MODEL") or "ninguno"
        print(f"Alerta: {alert}\nModelo: {os.environ['OPENAI_MODEL']} (respaldo: {fallback})\n")
        asyncio.run(run({"alert": alert}, thread_id))


if __name__ == "__main__":
    main()
