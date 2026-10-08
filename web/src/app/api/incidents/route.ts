import { injector, json } from "@/lib/backend";

/** Step 1: breaks the shop (injects the fault). The investigation starts later,
 *  once the symptoms are visible (see /api/investigations). */
export async function POST(request: Request) {
  const { scenario, variant } = await request.json();
  const injected = await injector("/injections", {
    method: "POST",
    headers: json,
    body: JSON.stringify({ scenario, variant }),
  });
  const body = await injected.json().catch(() => ({}));
  if (!injected.ok) {
    return Response.json({ detail: body?.detail ?? "the simulation could not start" }, { status: injected.status });
  }
  return Response.json({ injectedAt: body.injected_at });
}
