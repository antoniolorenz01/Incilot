"""Lanza una investigación sobre lo que esté pasando y muestra cada paso.

python -m incilot_agent.investigate ["descripción de la alerta"]
python -m incilot_agent.investigate --check-tools   # prueba cada herramienta una vez
"""

import asyncio
import json
import os
import sys

from langchain_openai import ChatOpenAI

from incilot_agent import graph
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


async def investigate(alert: str) -> None:
    llm = ChatOpenAI(model=os.environ["OPENAI_MODEL"], timeout=60, max_retries=2)
    app = graph.build(llm)
    print(f"Alerta: {alert}\nModelo: {os.environ['OPENAI_MODEL']}\n")
    final = {}
    async for update in app.astream({"alert": alert}, stream_mode="updates"):
        for node, change in update.items():
            final.update(change or {})
            if node == "triage":
                print("[triage] resumen del sistema listo")
            elif node == "agent":
                for call in change["messages"][-1].tool_calls:
                    args = json.dumps(call["args"], ensure_ascii=False)
                    print(f"\n[ronda {final.get('steps', 0) + 1}] {call['name']}({args[:200]})")
            elif node == "tools":
                for message in change["messages"]:
                    print(short(message.content))
    print(f"\n=== Diagnóstico ({final.get('stop_reason')}, {final.get('tokens', 0)} tokens) ===")
    print(json.dumps(final.get("diagnosis"), indent=2, ensure_ascii=False))


def main() -> None:
    if sys.argv[1:] == ["--check-tools"]:
        sys.exit(0 if asyncio.run(check_tools()) else 1)
    asyncio.run(investigate(" ".join(sys.argv[1:]) or DEFAULT_ALERT))


if __name__ == "__main__":
    main()
