import { injector, relay } from "@/lib/backend";

/** Ends the simulation: puts the shop back as it was. */
export async function POST() {
  return relay(await injector("/injections/active/recover", { method: "POST" }));
}
