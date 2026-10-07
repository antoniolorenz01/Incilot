// Tipos y estado de una investigación, construidos a partir de los eventos del agente.

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

export type AgentEvent =
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
  | { type: "done" };

export type Phase =
  | "idle"
  | "breaking" // la tienda está rota; esperamos a que aparezcan los síntomas
  | "investigating"
  | "awaiting_approval"
  | "executing"
  | "done"
  | "error";

/** Los pasos que ve el usuario (la barra de progreso). */
export const STEPS = ["Romper la tienda", "El agente investiga", "Vos decidís", "Resultado"] as const;

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

/** La respuesta correcta que guarda el injector. */
export type Truth = {
  scenario: string;
  variant: string;
  service: string;
  root_cause: string;
  action: string;
  culprit_sha: string | null;
  decoy_shas: string[];
};

/** Misma idea que las evals: ¿la acción propuesta arreglaría el incidente? */
export function grade(truth: Truth, diagnosis: Diagnosis) {
  const reverts = ["rollback", "revert_config"];
  const { kind, target } = diagnosis.action;
  const sameKind = kind === truth.action || (reverts.includes(kind) && reverts.includes(truth.action));
  const t = target.trim().toLowerCase();
  let action = false;
  if (sameKind) {
    if (reverts.includes(kind)) action = t.length >= 7 && (truth.culprit_sha ?? "").startsWith(t);
    else if (kind === "restart") action = t.includes(truth.service);
    else action = true;
  }
  const commit = diagnosis.culprit_commit?.toLowerCase() ?? "";
  return {
    action,
    service: new RegExp(`\\b${truth.service}\\b`, "i").test(diagnosis.service),
    commit: truth.culprit_sha
      ? commit.length >= 7 && truth.culprit_sha.startsWith(commit)
      : !diagnosis.culprit_commit,
    decoy: truth.decoy_shas.some((d) => commit.length >= 7 && d.startsWith(commit)),
  };
}
