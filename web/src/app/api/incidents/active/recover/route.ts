import { injector, relay } from "@/lib/backend";

/** Termina la simulación: deja la tienda como estaba. */
export async function POST() {
  return relay(await injector("/injections/active/recover", { method: "POST" }));
}
