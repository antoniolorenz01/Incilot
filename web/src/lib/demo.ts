// Server only (imported by the /api routes). The public demo has a single shop, so one
// simulation at a time: whoever starts it owns the turn (a cookie identifies them) and
// everyone else watches it live. Real investigations spend tokens, so on the public
// server (DEMO_LIMITS=on) there is a cap per IP and per day; dry runs are free.
//
// State lives in the agent's Redis, not the shop's: an incident that takes the shop's
// Redis down must not take the turns with it.

import { cookies, headers } from "next/headers";
import { createClient } from "redis";
import { agent, injector, json } from "@/lib/backend";

const REDIS_URL = process.env.DEMO_REDIS_URL ?? "redis://default:agent@localhost:6380/1";
const LIMITS = process.env.DEMO_LIMITS === "on";
const RUNS_PER_IP = Number(process.env.DEMO_RUNS_PER_IP ?? 2);
const RUNS_PER_DAY = Number(process.env.DEMO_RUNS_PER_DAY ?? 20);
// The longest a turn lasts, and how long it stays once the investigation has finished
// (so the owner can read the outcome before someone else takes over).
const TURN_MS = Number(process.env.DEMO_TURN_MINUTES ?? 12) * 60_000;
const AFTER_FINISH_MS = 2 * 60_000;

const TURN = "demo:turn";
const VISITOR = "incilot_visitor";

export type Turn = {
  owner: string;
  dryRun: boolean;
  startedAt: string;
  expiresAt: string;
  investigationId?: string;
  finished?: boolean;
};

type Refusal = { status: number; detail: string };

// One connection per server process (kept across hot reloads in development).
const global = globalThis as unknown as { demoRedis?: ReturnType<typeof connect> };

function connect() {
  return createClient({ url: REDIS_URL })
    .on("error", (error) => console.error("demo redis:", error))
    .connect();
}

function redis() {
  global.demoRedis ??= connect();
  return global.demoRedis;
}

/** The visitor's id: set on their first request, kept for 30 days. */
export async function visitor() {
  const jar = await cookies();
  const known = jar.get(VISITOR)?.value;
  if (known) return known;
  const id = crypto.randomUUID();
  jar.set(VISITOR, id, {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    maxAge: 30 * 24 * 60 * 60,
    path: "/",
  });
  return id;
}

/** The client's IP. In production Caddy sets X-Forwarded-For and discards whatever
 *  the client sent, so it cannot be spoofed. */
async function clientIp() {
  return (await headers()).get("x-forwarded-for")?.split(",")[0].trim() || "local";
}

// Replace the turn only if nobody changed it meanwhile (compare-and-set).
const SWAP = `
if redis.call('GET', KEYS[1]) == ARGV[1] then
  if ARGV[2] == '' then return redis.call('DEL', KEYS[1]) end
  return redis.call('SET', KEYS[1], ARGV[2])
end
return 0`;

async function swap(current: string, next: Turn | null) {
  const r = await redis();
  await r.eval(SWAP, { keys: [TURN], arguments: [current, next ? JSON.stringify(next) : ""] });
}

/** The ongoing turn, if any. Expired turns are closed here, lazily: whoever asks next
 *  rejects the abandoned decision and puts the shop back. */
export async function currentTurn(): Promise<Turn | null> {
  const raw = await (await redis()).get(TURN);
  if (!raw) return null;
  const turn = JSON.parse(raw) as Turn;
  if (Date.parse(turn.expiresAt) <= Date.now()) {
    await close(turn);
    await swap(raw, null);
    return null;
  }
  if (turn.investigationId && !turn.finished && (await finished(turn.investigationId))) {
    const expiresAt = new Date(Math.min(Date.parse(turn.expiresAt), Date.now() + AFTER_FINISH_MS));
    const updated = { ...turn, finished: true, expiresAt: expiresAt.toISOString() };
    await swap(raw, updated);
    return updated;
  }
  return turn;
}

async function finished(investigationId: string) {
  const response = await agent(`/investigations/${investigationId}`).catch(() => null);
  if (!response?.ok) return false;
  const { status } = await response.json();
  return status === "done" || status === "error";
}

async function close(turn: Turn) {
  if (turn.investigationId) {
    // If it was waiting for a decision, nobody is coming back to take it.
    await agent(`/investigations/${turn.investigationId}/approval`, {
      method: "POST",
      headers: json,
      body: JSON.stringify({ approved: false, note: "demo: the visitor left (turn expired)" }),
    }).catch(() => null);
  }
  await injector("/injections/active/recover", { method: "POST" }).catch(() => null);
}

/** Takes the turn to start a simulation, or says why not. */
export async function takeTurn(owner: string, dryRun: boolean): Promise<Turn | Refusal> {
  const current = await currentTurn();
  if (current) {
    return current.owner === owner
      ? { status: 409, detail: "you already have a simulation running" }
      : { status: 409, detail: "someone else is running a simulation: watch it live, it ends in a few minutes" };
  }
  const refund = dryRun ? null : await spend();
  if (refund && "status" in refund) return refund;

  const now = Date.now();
  const turn: Turn = {
    owner,
    dryRun,
    startedAt: new Date(now).toISOString(),
    expiresAt: new Date(now + TURN_MS).toISOString(),
  };
  const taken = await (await redis()).set(TURN, JSON.stringify(turn), { condition: "NX" });
  if (taken === null) {
    await refund?.();
    return { status: 409, detail: "someone else has just started a simulation: watch it live" };
  }
  return turn;
}

/** Counts a real investigation against the limits; returns how to undo it. */
async function spend(): Promise<(() => Promise<void>) | Refusal | null> {
  if (!LIMITS) return null;
  const r = await redis();
  const day = new Date().toISOString().slice(0, 10);
  const keys = [`demo:runs:${day}`, `demo:runs:${day}:${await clientIp()}`];
  const [today, mine] = await Promise.all(keys.map((key) => r.incr(key)));
  await Promise.all(keys.map((key) => r.expire(key, 2 * 24 * 60 * 60)));
  const refund = async () => {
    await Promise.all(keys.map((key) => r.decr(key)));
  };
  if (today > RUNS_PER_DAY || mine > RUNS_PER_IP) {
    await refund();
    const which =
      today > RUNS_PER_DAY
        ? "today’s real investigations have run out"
        : "you’ve used your real investigations for today";
    return { status: 429, detail: `${which}. Dry runs and past investigations are still available.` };
  }
  return refund;
}

/** The real investigations this visitor has left today (null without limits). */
export async function runsLeft(): Promise<number | null> {
  if (!LIMITS) return null;
  const r = await redis();
  const day = new Date().toISOString().slice(0, 10);
  const [today, mine] = await Promise.all([r.get(`demo:runs:${day}`), r.get(`demo:runs:${day}:${await clientIp()}`)]);
  return Math.max(0, Math.min(RUNS_PER_DAY - Number(today ?? 0), RUNS_PER_IP - Number(mine ?? 0)));
}

/** The owner's turn, or why they can't act on the simulation. */
export async function ownTurn(owner: string): Promise<Turn | Refusal> {
  const turn = await currentTurn();
  if (!turn) return { status: 409, detail: "there is no simulation running" };
  if (turn.owner !== owner) return { status: 403, detail: "this simulation belongs to another visitor" };
  return turn;
}

export async function attachInvestigation(turn: Turn, investigationId: string) {
  const raw = JSON.stringify(turn);
  await swap(raw, { ...turn, investigationId });
}

export async function releaseTurn(turn: Turn) {
  await swap(JSON.stringify(turn), null);
}

export function refused(result: Turn | Refusal): result is Refusal {
  return "status" in result;
}

export function refusal({ status, detail }: Refusal) {
  return Response.json({ detail }, { status });
}
