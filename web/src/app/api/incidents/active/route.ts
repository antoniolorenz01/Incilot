import { injector, relay } from "@/lib/backend";

/** The right answer for the active incident (to compare against the diagnosis). */
export async function GET() {
  return relay(await injector("/injections/active"));
}
