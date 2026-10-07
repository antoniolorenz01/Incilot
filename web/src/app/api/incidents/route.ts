import { injector, json } from "@/lib/backend";

/** Paso 1: rompe la tienda (inyecta el fallo). La investigación se lanza después,
 *  cuando ya aparecieron los síntomas (ver /api/investigations). */
export async function POST(request: Request) {
  const { scenario, variant } = await request.json();
  const injected = await injector("/injections", {
    method: "POST",
    headers: json,
    body: JSON.stringify({ scenario, variant }),
  });
  const body = await injected.json().catch(() => ({}));
  if (!injected.ok) {
    return Response.json({ detail: body?.detail ?? "no se pudo simular" }, { status: injected.status });
  }
  return Response.json({ injectedAt: body.injected_at });
}
