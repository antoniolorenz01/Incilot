"use client";

import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { toast } from "sonner";
import { DiagnosisPanel, type Decision } from "@/components/incident/diagnosis-panel";
import { SimulatePanel } from "@/components/incident/simulate-panel";
import { Terminal } from "@/components/incident/terminal";
import { type AgentEvent, type Investigation, type Truth, initial, reduce } from "@/lib/incident";

type Action = { type: "reset" } | { type: "start" } | { type: "event"; event: AgentEvent };

function reducer(state: Investigation, action: Action): Investigation {
  if (action.type === "reset") return initial;
  if (action.type === "start") return { ...initial, phase: "investigating" };
  return reduce(state, action.event);
}

const STATUS: Record<Investigation["phase"], { text: string; tone: string }> = {
  idle: { text: "Sin incidentes", tone: "text-muted-foreground" },
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

  const listen = useCallback((id: string) => {
    source.current?.close();
    const events = new EventSource(`/api/investigations/${id}/events`);
    events.onmessage = (message) => {
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

  useEffect(() => () => source.current?.close(), []);

  // La respuesta correcta se guarda en cuanto hay diagnóstico: después de resolver,
  // el injector ya no tiene un incidente activo para consultar.
  useEffect(() => {
    if (investigation.diagnosis && !truth) {
      fetch("/api/incidents/active")
        .then((r) => (r.ok ? r.json() : null))
        .then(setTruth)
        .catch(() => {});
    }
  }, [investigation.diagnosis, truth]);

  async function simulate(scenario: string, dryRun: boolean) {
    dispatch({ type: "start" });
    setTruth(null);
    const response = await fetch("/api/incidents", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ scenario, dryRun }),
    });
    const body = await response.json();
    if (!response.ok) {
      dispatch({ type: "reset" });
      toast.error(`No se pudo simular: ${body.detail}`);
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
    await fetch("/api/incidents/active/recover", { method: "POST" });
    source.current?.close();
    setInvestigationId(null);
    setTruth(null);
    dispatch({ type: "reset" });
  }

  const status = STATUS[investigation.phase];
  const busy = investigation.phase !== "idle" && investigation.phase !== "done" && investigation.phase !== "error";

  return (
    <main className="mx-auto flex w-full max-w-[1400px] flex-1 flex-col gap-4 p-4 md:p-6">
      <header className="flex flex-wrap items-end justify-between gap-4 border-b-2 border-foreground pb-4">
        <div>
          <h1 className="font-pixel text-4xl leading-none text-foreground md:text-5xl">IncidentPilot</h1>
          <p className="mt-2 max-w-[60ch] text-xs text-muted-foreground">
            Un agente investiga incidentes en una tienda de prueba, propone cómo arreglarlos y lo hace
            solo si vos lo aprobás.
          </p>
        </div>
        <p className={`font-pixel text-2xl ${status.tone}`} aria-live="polite">
          {status.text}
        </p>
      </header>

      <div className="grid min-h-0 flex-1 gap-4 lg:grid-cols-[280px_minmax(0,1fr)_400px]">
        <SimulatePanel busy={busy} onSimulate={simulate} />
        <Terminal events={investigation.events} phase={investigation.phase} />
        <DiagnosisPanel investigation={investigation} truth={truth} onDecide={decide} onEnd={end} />
      </div>
    </main>
  );
}
