import { currentTurn, runsLeft, visitor } from "@/lib/demo";

/** Who has the shop right now: the page uses it to resume your simulation or to watch
 *  someone else's live. Also how many real investigations you have left today. */
export async function GET() {
  const me = await visitor();
  const turn = await currentTurn();
  return Response.json({
    turn: turn && {
      mine: turn.owner === me,
      dryRun: turn.dryRun,
      startedAt: turn.startedAt,
      expiresAt: turn.expiresAt,
      investigationId: turn.investigationId ?? null,
    },
    runsLeft: await runsLeft(),
  });
}
