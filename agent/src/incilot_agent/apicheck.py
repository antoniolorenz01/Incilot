"""Prueba la API de punta a punta con una investigación dry_run (cero tokens).

    python -m incilot_agent.apicheck   # make agent-api-check, con `make up` corriendo

Lanza la investigación, la sigue por SSE hasta la pausa, la aprueba y sigue el
streaming hasta que termina. Imprime OK/FALLA por etapa.
"""

import json
import os
import sys

import httpx

API = os.getenv("AGENT_API_URL", "http://localhost:8200")


def check(label: str, ok: bool) -> bool:
    print(f"{'OK   ' if ok else 'FALLA'} {label}", flush=True)
    return ok


def events(client: httpx.Client, investigation_id: str):
    """Los eventos SSE como dicts, hasta que el servidor cierra el streaming."""
    url = f"/investigations/{investigation_id}/events"
    with client.stream("GET", url, timeout=120) as response:
        for line in response.iter_lines():
            if line.startswith("data: "):
                yield json.loads(line.removeprefix("data: "))


def main() -> bool:
    client = httpx.Client(base_url=API, timeout=10)
    started = client.post("/investigations", json={"alert": "apicheck", "dry_run": True})
    results = [check("POST /investigations encola la investigación", started.status_code == 202)]
    investigation_id = started.json()["id"]

    seen = []
    for event in events(client, investigation_id):
        seen.append(event["type"])
        if event["type"] == "awaiting_approval":
            approval = client.post(
                f"/investigations/{investigation_id}/approval", json={"approved": True}
            )
            results.append(
                check("POST .../approval acepta la decisión", approval.status_code == 202)
            )

    results += [
        check("el worker usó una herramienta real", "tool_result" in seen),
        check("SSE transmitió el diagnóstico", "diagnosis" in seen),
        check("la investigación se pausó para aprobación", "awaiting_approval" in seen),
        check(
            "aprobada → ejecución (dry_run: no ejecuta) → terminó",
            seen[-4:] == ["approval", "execution", "verification", "done"],
        ),
    ]
    final = client.get(f"/investigations/{investigation_id}").json()
    results.append(check("GET muestra el estado final", final.get("status") == "done"))
    print(f"\neventos: {' → '.join(seen)}")
    print(f"{sum(results)}/{len(results)} OK")
    return all(results)


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
