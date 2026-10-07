import { agent, json, relay } from "@/lib/backend";

export async function POST(request: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  return relay(
    await agent(`/investigations/${id}/approval`, {
      method: "POST",
      headers: json,
      body: await request.text(),
    }),
  );
}
