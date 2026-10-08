import { agent } from "@/lib/backend";

/** Relays the investigation's events live (SSE). */
export async function GET(request: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  // If the browser reconnects, resume from the last event it already has.
  const lastEventId = request.headers.get("last-event-id");
  const upstream = await agent(`/investigations/${id}/events`, {
    headers: lastEventId ? { "last-event-id": lastEventId } : {},
  });
  return new Response(upstream.body, {
    status: upstream.status,
    headers: {
      "content-type": "text/event-stream",
      "cache-control": "no-cache, no-transform",
      connection: "keep-alive",
    },
  });
}
