"""The agent's investigations, with state saved in Postgres (agent_state).

python -m incilot_agent.investigate ["alert description"]   # new
python -m incilot_agent.investigate --resume ID     # resumes from the last step
python -m incilot_agent.investigate --approve ID    # approves the proposed action
python -m incilot_agent.investigate --approve ID --target SHA [--kind K] [--note N]
                                                   # approves with a corrected action
python -m incilot_agent.investigate --reject ID     # rejects it
python -m incilot_agent.investigate --check-tools   # tries each tool once
python -m incilot_agent.investigate --selftest      # durable state, without an LLM
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
from incilot_agent.llm import agent_models, model_name
from incilot_agent.selftest import selftest
from incilot_agent.tools import READ_ONLY_TOOLS
from incilot_agent.verification import PostgresRecorder, PrometheusVerifier

DEFAULT_ALERT = "A degradation in the shop has been reported: customers are complaining."
CHECKS = {
    "query_metrics": {"promql": "sum by (service) (rate(http_requests_total[1m]))", "minutes": 5},
    "search_logs": {"level": "error", "minutes": 10, "limit": 3},
    "list_commits": {"since_minutes": 60 * 24 * 7, "limit": 3},
    "show_commit": {"sha": "HEAD"},
    "read_file": {"path": "config/shop.env"},
    "search_knowledge": {"query": "high latency in inventory", "limit": 1},
    "query_database": {"database": "inventory", "sql": "SELECT count(*) FROM pg_stat_activity"},
}


def short(text: str, lines: int = 3) -> str:
    rows = text.splitlines()
    more = f"\n      … ({len(rows) - lines} more lines)" if len(rows) > lines else ""
    return "\n".join(f"      {r[:160]}" for r in rows[:lines]) + more


async def check_tools() -> bool:
    ok = True
    for tool in READ_ONLY_TOOLS:
        result = await tool(**CHECKS[tool.__name__])
        failed = result.startswith("error:")
        ok &= not failed
        print(f"{'FAIL ' if failed else 'OK   '} {tool.__name__:16} {result.splitlines()[0][:100]}")
    return ok


def render(event: dict) -> str | None:
    """One console line per event (None: not shown)."""
    match event["type"]:
        case "triage":
            return "[triage] system overview ready"
        case "tool_call":
            args = json.dumps(event["args"], ensure_ascii=False)
            return f"\n[round {event['round']}] {event['name']}({args[:200]})"
        case "tool_result":
            return short(event["content"])
        case "llm_fallback":
            target = event["fallback_to"] or "no fallback"
            return f"\n[llm] {event['model']} failed ({event['error'][:80]}) → {target}"
        case "diagnosis":
            header = f"\n=== Diagnosis ({event['stop_reason']}, {event['tokens']} tokens) ==="
            return header + "\n" + json.dumps(event["diagnosis"], indent=2, ensure_ascii=False)
        case "approval":
            verdict = "APPROVED" if event["approved"] else "REJECTED"
            return f"\nAction {verdict} by {event['by']}"
        case "execution":
            return f"[execution] {event['status']} ({event['connector']}): {event['detail']}"
        case "verification":
            if event.get("skipped"):
                return "[verification] not verified: the action was not executed"
            lines = [
                f"  {'OK' if c['ok'] else '✗ '} {c['name']}: {c['value']} (max {c['max']})"
                for c in event["checks"]
            ]
            verdict = "RESOLVED" if event["recovered"] else "PROBLEM PERSISTS"
            return f"[verification] {verdict}\n" + "\n".join(lines)
    return None


async def run(graph_input, thread_id: str) -> None:
    run_config = {"configurable": {"thread_id": thread_id}}
    async with AsyncPostgresSaver.from_conn_string(config.AGENT_STATE_URL) as checkpointer:
        await checkpointer.setup()
        app = graph.build(
            agent_models(),
            checkpointer,
            executor=default_executor(),
            verifier=PrometheusVerifier(),
            recorder=PostgresRecorder(),
        )
        if graph_input is None and not (await app.aget_state(run_config)).values:
            print(f"investigation {thread_id} does not exist")
            return
        async for event in investigation_events(app, graph_input, run_config):
            if line := render(event):
                print(line)
            if event["type"] == "awaiting_approval":
                print("\nAwaiting approval of the proposed action. To decide:")
                print(f'  make investigate ARGS="--approve {thread_id}"   (or --reject)')


def main() -> None:
    parser = argparse.ArgumentParser(description="IncidentPilot investigations")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--resume", metavar="ID")
    group.add_argument("--approve", metavar="ID")
    group.add_argument("--reject", metavar="ID")
    group.add_argument("--check-tools", action="store_true")
    group.add_argument("--selftest", action="store_true")
    parser.add_argument("--kind", help="when approving: correct the action kind")
    parser.add_argument("--target", help="when approving: correct the target (commit, service…)")
    parser.add_argument("--note", default="", help="when approving or rejecting: a comment")
    parser.add_argument("alert", nargs="*", help="alert description")
    args = parser.parse_args()

    if args.check_tools:
        raise SystemExit(0 if asyncio.run(check_tools()) else 1)
    if args.selftest:
        raise SystemExit(0 if asyncio.run(selftest()) else 1)
    if args.resume:
        print(f"Resuming investigation {args.resume}")
        asyncio.run(run(None, args.resume))
    elif args.approve or args.reject:
        override = {k: v for k, v in {"kind": args.kind, "target": args.target}.items() if v}
        decision = {
            "approved": bool(args.approve),
            "by": os.getenv("USER", "on-call"),
            "note": args.note,
            "action": override or None,
        }
        asyncio.run(run(Command(resume=decision), args.approve or args.reject))
    else:
        thread_id = uuid4().hex[:12]
        alert = " ".join(args.alert) or DEFAULT_ALERT
        print(f"Investigation {thread_id} (if interrupted: --resume {thread_id})")
        models = ", ".join(model_name(m) for m in agent_models())
        print(f"Alert: {alert}\nModels (in order of preference): {models}\n")
        asyncio.run(run({"alert": alert}, thread_id))


if __name__ == "__main__":
    main()
