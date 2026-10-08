import { agent, injector, json } from "@/lib/backend";

/** Step 2: starts the agent's investigation into the ongoing incident. */
export async function POST(request: Request) {
  const { since, dryRun } = await request.json();
  const investigation = await agent("/investigations", {
    method: "POST",
    headers: json,
    body: JSON.stringify({
      alert: `Shop degraded since ${since} UTC: customers are complaining.`,
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
