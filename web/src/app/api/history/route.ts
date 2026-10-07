import { agent, relay } from "@/lib/backend";

/** Investigaciones anteriores (ya decididas). */
export async function GET() {
  return relay(await agent("/incidents?limit=20"));
}
