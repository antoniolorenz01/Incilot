import { injector, relay } from "@/lib/backend";

export async function GET() {
  return relay(await injector("/scenarios"));
}
