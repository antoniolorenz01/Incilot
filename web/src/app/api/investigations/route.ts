import { agent, injector, json } from "@/lib/backend";

/** Paso 2: lanza la investigación del agente sobre el incidente en curso. */
export async function POST(request: Request) {
  const { since, dryRun } = await request.json();
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
