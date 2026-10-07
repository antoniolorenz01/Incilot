"use client";

import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { DiagnosisPanel, type Decision } from "@/components/incident/diagnosis-panel";
import { History } from "@/components/incident/history";
import { COLUMNS, Status, Steps } from "@/components/incident/progress";
import { ResultPanel } from "@/components/incident/result-panel";
import { ShopHealth } from "@/components/incident/shop-health";
import { SimulatePanel } from "@/components/incident/simulate-panel";
import { Terminal } from "@/components/incident/terminal";
import { type AgentEvent, type Investigation, type Truth, initial, reduce } from "@/lib/incident";

type Action =
  | { type: "reset" }
  | { type: "breaking" }
  | { type: "investigating" }
  | { type: "event"; event: AgentEvent };

function reducer(state: Investigation, action: Action): Investigation {
  if (action.type === "reset") return initial;
  if (action.type === "breaking") return { ...initial, phase: "breaking" };
  if (action.type === "investigating") return { ...state, phase: "investigating" };
  return reduce(state, action.event);
}

// Cuánto esperar a que los síntomas sean visibles antes de llamar al agente.
const WARMUP_MS = 60_000;
const DRY_RUN_WARMUP_MS = 5_000;

function deadlineIn(ms: number) {
  return Date.now() + ms;
}

const STATUS: Record<Investigation["phase"], { text: string; tone: string }> = {
  idle: { text: "Sin incidentes", tone: "text-muted-foreground" },
  breaking: { text: "Incidente en curso", tone: "text-accent" },
  investigating: { text: "Investigando", tone: "text-accent" },
  awaiting_approval: { text: "Espera tu decisión", tone: "text-accent" },
  executing: { text: "Aplicando la solución", tone: "text-accent" },
  done: { text: "Terminado", tone: "text-foreground" },
  error: { text: "Falló la investigación", tone: "text-destructive" },
};

export default function Home() {
  const [investigation, dispatch] = useReducer(reducer, initial);
  const [investigationId, setInvestigationId] = useState<string | null>(null);
  const [truth, setTruth] = useState<Truth | null>(null);
  const source = useRef<EventSource | null>(null);
  const warmupTimer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const [countdownTo, setCountdownTo] = useState<number | null>(null);
  // Una simulación que ya estaba activa al abrir la página (p. ej. de otra pestaña).
  const [leftover, setLeftover] = useState<string | null>(null);
  // Mirando una investigación anterior (se reproduce, no se puede decidir).
  const [readOnly, setReadOnly] = useState(false);

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
      // Un evento `error` sin datos es el de EventSource (conexión caída), no el del
      // agente: el navegador reintenta solo y retomamos desde el último evento.
      if (!message.data) return;
      const event = JSON.parse(message.data) as AgentEvent;
      dispatch({ type: "event", event });
      if (event.type === "done" || event.type === "error") events.close();
    };
    // El servidor emite eventos con nombre (event: tool_call…): escuchamos todos.
    for (const type of ["triage", "tool_call", "tool_result", "llm_fallback", "diagnosis",
      "awaiting_approval", "approval", "execution", "verification", "error", "done"]) {
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

  // La respuesta correcta se guarda en cuanto hay diagnóstico: después de resolver,
  // el injector ya no tiene un incidente activo para consultar.
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
    listen(id); // el stream reenvía la historia completa
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
      toast.error(`No se pudo simular: ${body.detail}`);
      return;
    }
    // Como una alerta real: el agente arranca cuando los síntomas ya se ven.
    const since = new Date().toISOString().slice(11, 16);
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
      toast.error(`No se pudo investigar: ${body.detail}`);
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
    // La conexión de eventos sigue abierta: la ejecución y la verificación llegan por ahí.
    if (!response.ok) toast.error("No se pudo registrar tu decisión.");
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
  const busy = investigation.phase !== "idle" && investigation.phase !== "done" && investigation.phase !== "error";

  return (
    <main className="mx-auto flex h-dvh w-full max-w-[1920px] flex-col gap-3 overflow-hidden p-3 md:p-4">
      <header className="flex shrink-0 flex-wrap items-end justify-between gap-3 border-b-2 border-foreground pb-3">
        <div className="min-w-0">
          <h1 className="font-pixel text-3xl leading-none text-foreground md:text-4xl">IncidentPilot</h1>
          <p className="mt-1.5 max-w-[70ch] text-xs text-muted-foreground">
            Un agente investiga incidentes en una tienda de prueba, propone cómo arreglarlos y lo hace
            solo si vos lo aprobás.
          </p>
        </div>
        <p className={`font-pixel text-xl ${readOnly ? "text-muted-foreground" : status.tone}`} aria-live="polite">
          {readOnly ? "Investigación anterior" : status.text}
        </p>
      </header>

      <div className="shrink-0 space-y-2">
        <Steps phase={investigation.phase} />
        {!readOnly && <Status key={investigation.phase} phase={investigation.phase} countdownTo={countdownTo} />}
        {leftover && investigation.phase === "idle" && (
          <div role="status" className="flex flex-wrap items-center justify-between gap-3 border-2 border-accent p-3 text-xs">
            <p className="text-foreground">
              Hay una simulación activa desde las{" "}
              {new Date(leftover).toLocaleTimeString("es", { hour: "2-digit", minute: "2-digit" })}. Terminala
              para simular otra.
            </p>
            <Button size="sm" variant="outline" onClick={end}>
              Terminarla
            </Button>
          </div>
        )}
      </div>

      {/* La pantalla no hace scroll: cada panel scrollea por dentro. */}
      {/* Una columna por paso: romper, investigar, decidir, resultado. */}
      <div className={`grid min-h-0 flex-1 gap-3 max-xl:overflow-y-auto ${COLUMNS}`}>
        {/* Si el alto no alcanza (p. ej. con el aviso de «Rompiendo la tienda»), la
            columna scrollea en vez de aplastar los gráficos. */}
        <div className="flex min-h-0 flex-col gap-3 overflow-y-auto">
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
  );
}
