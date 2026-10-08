// Types and state of an investigation, built from the agent's events.

export type Action = { kind: string; target: string; reason: string; evidence: string[] };

export type Diagnosis = {
  service: string;
  root_cause: string;
  culprit_commit: string | null;
  evidence: string[];
  confidence: "low" | "medium" | "high";
  plan: string[];
  action: Action;
};

export type Check = { name: string; value: number; max: number; ok: boolean };

// `at`: when the agent published it (ms), taken from the event id in the stream.
export type AgentEvent = (
  | { type: "triage" }
  | { type: "tool_call"; name: string; args: Record<string, unknown>; round: number }
  | { type: "tool_result"; name: string; content: string }
  | { type: "llm_fallback"; model: string; error: string; fallback_to: string | null }
  | { type: "diagnosis"; diagnosis: Diagnosis; stop_reason: string; tokens: number }
  | { type: "awaiting_approval" }
  | { type: "approval"; approved: boolean; by: string; note: string }
  | { type: "execution"; status: string; detail: string; connector: string }
  | { type: "verification"; recovered: boolean; checks: Check[]; skipped?: boolean }
  | { type: "error"; error: string }
  | { type: "done" }
) & { at?: number };

export type Phase =
  | "idle"
  | "breaking" // the shop is broken; waiting for the symptoms to show
  | "investigating"
  | "awaiting_approval"
  | "executing"
  | "done"
  | "error";

/** The steps the user sees (the progress bar). */
export const STEPS = ["Break the shop", "The agent investigates", "You decide", "Outcome"] as const;

export function stepOf(phase: Phase): number {
  return { idle: -1, breaking: 0, investigating: 1, awaiting_approval: 2, executing: 3, done: 3, error: 1 }[phase];
}

export type Investigation = {
  phase: Phase;
  events: AgentEvent[];
  diagnosis?: Diagnosis;
  tokens?: number;
  execution?: Extract<AgentEvent, { type: "execution" }>;
  verification?: Extract<AgentEvent, { type: "verification" }>;
  approved?: boolean;
  error?: string;
};

export const initial: Investigation = { phase: "idle", events: [] };

export function reduce(state: Investigation, event: AgentEvent): Investigation {
  const next = { ...state, events: [...state.events, event] };
  switch (event.type) {
    case "diagnosis":
      return { ...next, diagnosis: event.diagnosis, tokens: event.tokens };
    case "awaiting_approval":
      return { ...next, phase: "awaiting_approval" };
    case "approval":
      return { ...next, phase: event.approved ? "executing" : "done", approved: event.approved };
    case "execution":
      return { ...next, execution: event };
    case "verification":
      return { ...next, verification: event };
    case "error":
      return { ...next, phase: "error", error: event.error };
    case "done":
      return { ...next, phase: "done" };
    default:
      return next;
  }
}

/** The right answer, as stored by the injector. */
/** A recorded investigation (web/public/replays, made with `make record`). */
export type Replay = {
  scenario: string;
  variant: string;
  /** Which model investigated. */
  model: string;
  recordedAt: string;
  /** When the fault was injected (ms). */
  injectedAt: number;
  truth: Truth;
  events: (AgentEvent & { at: number })[];
  /** The "Shop health" series: [ms, value] every 15 s, from 15 min before the fault. */
  health: Record<string, [number, number][]>;
};

/** An entry of web/public/replays/index.json. */
export type ReplayEntry = {
  file: string;
  scenario: string;
  variant: string;
  title: string;
  category: string;
  recordedAt: string;
};

export type Truth = {
  scenario: string;
  variant: string;
  service: string;
  root_cause: string;
  action: string;
  culprit_sha: string | null;
  decoy_shas: string[];
};

function commitsIn(text: string): string[] {
  return text.match(/\b[0-9a-f]{7,40}\b/g) ?? [];
}

/** Same idea as the evals: would the proposed action fix the incident? */
export function grade(truth: Truth, diagnosis: Diagnosis) {
  const reverts = ["rollback", "revert_config"];
  const { kind, target } = diagnosis.action;
  const sameKind = kind === truth.action || (reverts.includes(kind) && reverts.includes(truth.action));
  const t = target.trim().toLowerCase();
  let action = false;
  if (sameKind) {
    // The agent may write just the SHA or e.g. "config/users.env (commit 5eb28d2)".
    if (reverts.includes(kind)) action = commitsIn(t).some((sha) => (truth.culprit_sha ?? "").startsWith(sha));
    else if (kind === "restart") action = t.includes(truth.service);
    else action = true;
  }
  const commit = diagnosis.culprit_commit?.toLowerCase() ?? "";
  return {
    action,
    service: new RegExp(`\\b${truth.service}\\b`, "i").test(diagnosis.service),
    commit: truth.culprit_sha ? commit.length >= 7 && truth.culprit_sha.startsWith(commit) : !diagnosis.culprit_commit,
    decoy: truth.decoy_shas.some((d) => commit.length >= 7 && d.startsWith(commit)),
  };
}
