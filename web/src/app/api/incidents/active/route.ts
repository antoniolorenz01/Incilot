import { injector, relay } from "@/lib/backend";

/** La respuesta correcta del incidente activo (para compararla con el diagnóstico). */
export async function GET() {
  return relay(await injector("/injections/active"));
}
