import { agent, injector, json } from "@/lib/backend";
import { attachInvestigation, ownTurn, refusal, refused, releaseTurn, visitor } from "@/lib/demo";

/** Step 2: starts the agent's investigation into the ongoing incident. */
export async function POST(request: Request) {
  const turn = await ownTurn(await visitor());
  if (refused(turn)) return refusal(turn);
  const { since } = await request.json();
  // When the incident started: the alert says it, and the triage counts from then on
  // (so a previous incident's leftovers are not taken for this one).
  const start = new Date(since);
  const investigation = await agent("/investigations", {
    method: "POST",
    headers: json,
    body: JSON.stringify({
      alert: `Shop degraded since ${start.toISOString().slice(11, 19)} UTC: customers are complaining.`,
      since: start.toISOString(),
      // From the turn, not the request: a free dry-run turn can't start a real investigation.
      dry_run: turn.dryRun,
    }),
  });
  if (!investigation.ok) {
    await injector("/injections/active/recover", { method: "POST" });
    await releaseTurn(turn);
    return Response.json({ detail: "the agent did not respond" }, { status: 502 });
  }
  const { id } = await investigation.json();
  await attachInvestigation(turn, id);
  return Response.json({ investigationId: id });
}
