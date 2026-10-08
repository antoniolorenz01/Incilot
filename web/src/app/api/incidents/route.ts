import { refusal, refused, releaseTurn, takeTurn, visitor } from "@/lib/demo";
import { injector, json } from "@/lib/backend";

/** Step 1: breaks the shop (injects the fault). The investigation starts later,
 *  once the symptoms are visible (see /api/investigations). One at a time: whoever
 *  starts it owns the turn. */
export async function POST(request: Request) {
  const { scenario, variant, dryRun } = await request.json();
  const turn = await takeTurn(await visitor(), Boolean(dryRun));
  if (refused(turn)) return refusal(turn);

  const injected = await injector("/injections", {
    method: "POST",
    headers: json,
    body: JSON.stringify({ scenario, variant }),
  });
  const body = await injected.json().catch(() => ({}));
  if (!injected.ok) {
    await releaseTurn(turn);
    return Response.json({ detail: body?.detail ?? "the simulation could not start" }, { status: injected.status });
  }
  return Response.json({ injectedAt: body.injected_at });
}
