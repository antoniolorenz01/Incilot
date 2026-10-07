import { agent, injector, json } from "@/lib/backend";

/** Simula un incidente: lo inyecta y lanza la investigación del agente. */
export async function POST(request: Request) {
  const { scenario, variant, dryRun } = await request.json();

  const injected = await injector("/injections", {
    method: "POST",
    headers: json,
    body: JSON.stringify({ scenario, variant }),
  });
  if (!injected.ok) {
    const detail = (await injected.json().catch(() => ({})))?.detail ?? "no se pudo simular";
    return Response.json({ detail }, { status: injected.status });
  }

  const since = new Date().toISOString().slice(11, 16);
  const investigation = await agent("/investigations", {
    method: "POST",
    headers: json,
    body: JSON.stringify({
      alert: `Degradación en la tienda desde las ${since} UTC: hay quejas de clientes.`,
      dry_run: Boolean(dryRun),
    }),
  });
  if (!investigation.ok) {
    await injector("/injections/active/recover", { method: "POST" });
    return Response.json({ detail: "el agente no respondió" }, { status: 502 });
  }
  const { id } = await investigation.json();
  return Response.json({ investigationId: id });
}
