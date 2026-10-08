import { agent, relay } from "@/lib/backend";

/** Past investigations (already decided). */
export async function GET() {
  return relay(await agent("/incidents?limit=20"));
}
