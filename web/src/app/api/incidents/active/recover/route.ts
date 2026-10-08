import { injector, relay } from "@/lib/backend";
import { currentTurn, releaseTurn, visitor } from "@/lib/demo";

/** Ends the simulation: puts the shop back as it was. Only its owner can, or anyone
 *  if it has no owner (started outside the web, e.g. by the evals). */
export async function POST() {
  const turn = await currentTurn();
  if (turn && turn.owner !== (await visitor())) {
    return Response.json({ detail: "this simulation belongs to another visitor" }, { status: 403 });
  }
  const recovered = await injector("/injections/active/recover", { method: "POST" });
  if (turn) await releaseTurn(turn);
  return relay(recovered);
}
