"""End-to-end test of the API with a dry_run investigation (zero tokens).

    python -m incilot_agent.apicheck   # make agent-api-check, with `make up` running

Starts the investigation, follows it over SSE until it pauses, approves it and follows
the stream until it finishes. Prints OK/FAIL per stage.
"""

import json
import os
import sys

import httpx

API = os.getenv("AGENT_API_URL", "http://localhost:8200")


def check(label: str, ok: bool) -> bool:
    print(f"{'OK   ' if ok else 'FAIL '} {label}", flush=True)
    return ok


def events(client: httpx.Client, investigation_id: str):
    """The SSE events as dicts, until the server closes the stream."""
    url = f"/investigations/{investigation_id}/events"
    with client.stream("GET", url, timeout=120) as response:
        for line in response.iter_lines():
            if line.startswith("data: "):
                yield json.loads(line.removeprefix("data: "))


def main() -> bool:
    client = httpx.Client(base_url=API, timeout=10)
    started = client.post("/investigations", json={"alert": "apicheck", "dry_run": True})
    results = [check("POST /investigations queues the investigation", started.status_code == 202)]
    investigation_id = started.json()["id"]

    seen = []
    for event in events(client, investigation_id):
        seen.append(event["type"])
        if event["type"] == "awaiting_approval":
            approval = client.post(
                f"/investigations/{investigation_id}/approval", json={"approved": True}
            )
            results.append(
                check("POST .../approval accepts the decision", approval.status_code == 202)
            )

    results += [
        check("the worker used a real tool", "tool_result" in seen),
        check("SSE streamed the diagnosis", "diagnosis" in seen),
        check("the investigation paused for approval", "awaiting_approval" in seen),
        check(
            "approved → execution (dry_run: nothing executed) → finished",
            seen[-4:] == ["approval", "execution", "verification", "done"],
        ),
    ]
    final = client.get(f"/investigations/{investigation_id}").json()
    results.append(check("GET shows the final status", final.get("status") == "done"))
    print(f"\nevents: {' → '.join(seen)}")
    print(f"{sum(results)}/{len(results)} OK")
    return all(results)


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
