import { agent, injector, json } from "@/lib/backend";

/** Step 2: starts the agent's investigation into the ongoing incident. */
export async function POST(request: Request) {
  const { since, dryRun } = await request.json();
  const investigation = await agent("/investigations", {
    method: "POST",
    headers: json,
    body: JSON.stringify({
      // The alert stays in Spanish, the agent's prompt language, until the agent is translated.
      alert: `Degradación en la tienda desde las ${since} UTC: hay quejas de clientes.`,
      dry_run: Boolean(dryRun),
    }),
  });
  if (!investigation.ok) {
    await injector("/injections/active/recover", { method: "POST" });
    return Response.json({ detail: "the agent did not respond" }, { status: 502 });
  }
  const { id } = await investigation.json();
  return Response.json({ investigationId: id });
}
