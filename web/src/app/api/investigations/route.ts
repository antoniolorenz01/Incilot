import { agent, injector, json } from "@/lib/backend";

/** Step 2: starts the agent's investigation into the ongoing incident. */
export async function POST(request: Request) {
  const { since, dryRun } = await request.json();
  // When the incident started: the alert says it, and the triage counts from then on
  // (so a previous incident's leftovers are not taken for this one).
  const start = new Date(since);
  const investigation = await agent("/investigations", {
    method: "POST",
    headers: json,
    body: JSON.stringify({
      alert: `Shop degraded since ${start.toISOString().slice(11, 19)} UTC: customers are complaining.`,
      since: start.toISOString(),
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
