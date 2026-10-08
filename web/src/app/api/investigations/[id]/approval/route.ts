import { agent, json, relay } from "@/lib/backend";
import { ownTurn, refusal, refused, visitor } from "@/lib/demo";

/** Step 3: the human decision. Only the visitor who started the simulation decides. */
export async function POST(request: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const turn = await ownTurn(await visitor());
  if (refused(turn)) return refusal(turn);
  if (turn.investigationId !== id) {
    return Response.json({ detail: "that investigation is not the one running" }, { status: 409 });
  }
  return relay(
    await agent(`/investigations/${id}/approval`, {
      method: "POST",
      headers: json,
      body: await request.text(),
    }),
  );
}
