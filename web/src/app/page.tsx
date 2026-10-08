"use client";

import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { DiagnosisPanel, type Decision } from "@/components/incident/diagnosis-panel";
import { History } from "@/components/incident/history";
import { Architecture } from "@/components/incident/architecture";
import { Explain, TechMode } from "@/components/incident/explain";
import { COLUMNS, Status, Steps } from "@/components/incident/progress";
import { Switch } from "@/components/ui/switch";
import { FOCUS } from "@/lib/explain";
import { ResultPanel } from "@/components/incident/result-panel";
import { ShopHealth } from "@/components/incident/shop-health";
import { SimulatePanel } from "@/components/incident/simulate-panel";
import { Terminal } from "@/components/incident/terminal";
import { type AgentEvent, type Investigation, type Truth, initial, reduce } from "@/lib/incident";

type Action =
  { type: "reset" } | { type: "breaking" } | { type: "investigating" } | { type: "event"; event: AgentEvent };

function reducer(state: Investigation, action: Action): Investigation {
  if (action.type === "reset") return initial;
  if (action.type === "breaking") return { ...initial, phase: "breaking" };
  if (action.type === "investigating") return { ...state, phase: "investigating" };
  return reduce(state, action.event);
}

// How long to wait for the symptoms to show before calling the agent.
const WARMUP_MS = 60_000;
const DRY_RUN_WARMUP_MS = 5_000;

function deadlineIn(ms: number) {
  return Date.now() + ms;
}

const STATUS: Record<Investigation["phase"], { text: string; tone: string }> = {
  idle: { text: "No incidents", tone: "text-muted-foreground" },
  breaking: { text: "Incident in progress", tone: "text-accent" },
  investigating: { text: "Investigating", tone: "text-accent" },
  awaiting_approval: { text: "Awaiting your decision", tone: "text-accent" },
  executing: { text: "Applying the fix", tone: "text-accent" },
  done: { text: "Finished", tone: "text-foreground" },
  error: { text: "Investigation failed", tone: "text-destructive" },
};

export default function Home() {
  const [investigation, dispatch] = useReducer(reducer, initial);
  const [investigationId, setInvestigationId] = useState<string | null>(null);
  const [truth, setTruth] = useState<Truth | null>(null);
  const source = useRef<EventSource | null>(null);
  const warmupTimer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const [countdownTo, setCountdownTo] = useState<number | null>(null);
  // A simulation that was already active when the page opened (e.g. from another tab).
  const [leftover, setLeftover] = useState<string | null>(null);
  // Viewing a past investigation (it's replayed; no decision possible).
  const [readOnly, setReadOnly] = useState(false);
  const [tech, setTech] = useState(false);

  useEffect(() => {
    fetch("/api/incidents/active")
      .then((r) => (r.ok ? r.json() : null))
      .then((active) => active && setLeftover(String(active.injected_at)))
      .catch(() => {});
  }, []);

  const listen = useCallback((id: string) => {
    source.current?.close();
    const events = new EventSource(`/api/investigations/${id}/events`);
    events.onmessage = (message) => {
      // An `error` event with no data is EventSource's (connection lost), not the agent's:
      // the browser retries on its own and we resume from the last event.
      if (!message.data) return;
      // The event id is the Redis stream's: "<ms>-<n>", when it was published.
      const at = Number(message.lastEventId.split("-")[0]) || undefined;
      const event = { ...(JSON.parse(message.data) as AgentEvent), at };
      dispatch({ type: "event", event });
      if (event.type === "done" || event.type === "error") events.close();
    };
    // The server sends named events (event: tool_call…): listen to all of them.
    for (const type of [
      "triage",
      "tool_call",
      "tool_result",
      "llm_fallback",
      "diagnosis",
      "awaiting_approval",
      "approval",
      "execution",
      "verification",
      "error",
      "done",
    ]) {
      events.addEventListener(type, events.onmessage as EventListener);
    }
    source.current = events;
  }, []);

  useEffect(
    () => () => {
      source.current?.close();
      clearTimeout(warmupTimer.current);
    },
    [],
  );

  // Store the right answer as soon as there is a diagnosis: once resolved, the
  // injector no longer has an active incident to ask about.
  useEffect(() => {
    if (investigation.diagnosis && !truth && !readOnly) {
      fetch("/api/incidents/active")
        .then((r) => (r.ok ? r.json() : null))
        .then(setTruth)
        .catch(() => {});
    }
  }, [investigation.diagnosis, truth, readOnly]);

  function openPast(id: string) {
    clearTimeout(warmupTimer.current);
    setCountdownTo(null);
    setTruth(null);
    setReadOnly(true);
    setInvestigationId(id);
    dispatch({ type: "investigating" });
    listen(id); // the stream replays the full history
  }

  async function simulate(scenario: string, dryRun: boolean) {
    dispatch({ type: "breaking" });
    setReadOnly(false);
    setTruth(null);
    const response = await fetch("/api/incidents", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ scenario }),
    });
    const body = await response.json();
    if (!response.ok) {
      dispatch({ type: "reset" });
      if (response.status === 409) setLeftover(new Date().toISOString());
      toast.error(`Could not simulate: ${body.detail}`);
      return;
    }
    // Like a real alert: the agent starts once the symptoms are visible.
    const since: string = body.injectedAt ?? new Date().toISOString();
    const warmup = dryRun ? DRY_RUN_WARMUP_MS : WARMUP_MS;
    setCountdownTo(deadlineIn(warmup));
    warmupTimer.current = setTimeout(() => investigate(since, dryRun), warmup);
  }

  async function investigate(since: string, dryRun: boolean) {
    setCountdownTo(null);
    dispatch({ type: "investigating" });
    const response = await fetch("/api/investigations", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ since, dryRun }),
    });
    const body = await response.json();
    if (!response.ok) {
      dispatch({ type: "reset" });
      toast.error(`Could not investigate: ${body.detail}`);
      return;
    }
    setInvestigationId(body.investigationId);
    listen(body.investigationId);
  }

  async function decide(decision: Decision) {
    if (!investigationId) return;
    const response = await fetch(`/api/investigations/${investigationId}/approval`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(decision),
    });
    // The event connection stays open: execution and verification arrive through it.
    if (!response.ok) toast.error("Could not record your decision.");
  }

  async function end() {
    clearTimeout(warmupTimer.current);
    setCountdownTo(null);
    if (!readOnly) await fetch("/api/incidents/active/recover", { method: "POST" });
    setReadOnly(false);
    setLeftover(null);
    source.current?.close();
    setInvestigationId(null);
    setTruth(null);
    dispatch({ type: "reset" });
  }

  const status = STATUS[investigation.phase];
  const focus = readOnly ? null : FOCUS[investigation.phase];
  const busy = investigation.phase !== "idle" && investigation.phase !== "done" && investigation.phase !== "error";

  return (
    <TechMode value={tech}>
      <main className="mx-auto flex h-dvh w-full max-w-[1920px] flex-col gap-3 overflow-hidden p-3 md:p-4">
        <header className="flex shrink-0 flex-wrap items-end justify-between gap-3 border-b-2 border-foreground pb-3">
          <div className="min-w-0">
            <h1 className="font-pixel text-3xl leading-none text-foreground md:text-4xl">IncidentPilot</h1>
            <p className="mt-1.5 max-w-[70ch] text-xs text-muted-foreground">
              An agent investigates incidents in a test shop, proposes how to fix them and only does so once you
              approve.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            <p className={`font-pixel text-xl ${readOnly ? "text-muted-foreground" : status.tone}`} aria-live="polite">
              {readOnly ? "Past investigation" : status.text}
            </p>
            <Architecture />
            <label className="flex items-center gap-2 text-xs text-muted-foreground">
              <Switch checked={tech} onCheckedChange={setTech} />
              Technical mode
            </label>
            <Explain topic="tech" />
          </div>
        </header>

        <div className="shrink-0 space-y-2">
          <Steps phase={investigation.phase} hint={focus?.hint} />
          {!readOnly && <Status key={investigation.phase} phase={investigation.phase} countdownTo={countdownTo} />}
          {leftover && investigation.phase === "idle" && (
            <div
              role="status"
              className="flex flex-wrap items-center justify-between gap-3 border-2 border-accent p-3 text-xs"
            >
              <p className="text-foreground">
                A simulation has been active since{" "}
                {new Date(leftover).toLocaleTimeString("en-GB", {
                  hour: "2-digit",
                  minute: "2-digit",
                })}
                . End it to simulate another.
              </p>
              <Button size="sm" variant="outline" onClick={end}>
                End it
              </Button>
            </div>
          )}
        </div>

        {/* The page doesn't scroll: each panel scrolls inside. */}
        {/* One column per step: break, investigate, decide, outcome. */}
        <div
          className={`focus-columns grid min-h-0 flex-1 gap-3 max-xl:overflow-y-auto ${COLUMNS}`}
          data-focus={focus?.columns.map((c) => `c${c}`).join(" ")}
        >
          {/* Same height as the other columns: each panel scrolls inside. */}
          <div className="flex min-h-0 flex-col gap-3">
            <SimulatePanel busy={busy} onSimulate={simulate} onCancel={end} />
            <ShopHealth />
          </div>
          <Terminal events={investigation.events} phase={investigation.phase} />
          <DiagnosisPanel investigation={investigation} readOnly={readOnly} onDecide={decide} />
          <div className="flex min-h-0 flex-col gap-3">
            <ResultPanel
              key={investigationId ?? "none"}
              investigation={investigation}
              truth={truth}
              readOnly={readOnly}
              onEnd={end}
            />
            <History refreshKey={investigation.phase === "done" ? (investigationId ?? "") : ""} onOpen={openPast} />
          </div>
        </div>
      </main>
    </TechMode>
  );
}
