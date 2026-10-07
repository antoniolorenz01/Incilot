import { agent } from "@/lib/backend";

/** Reenvía en vivo los eventos (SSE) de la investigación. */
export async function GET(request: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  // Si el navegador se reconecta, retomamos desde el último evento que ya tiene.
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
