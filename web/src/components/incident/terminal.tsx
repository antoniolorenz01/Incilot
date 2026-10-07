"use client";

import { useEffect, useRef } from "react";
import type { AgentEvent, Phase } from "@/lib/incident";

const ACTIONS: Record<string, string> = {
  rollback: "revertir un deploy",
  revert_config: "revertir un cambio de config",
  restart: "reiniciar",
  terminate_session: "terminar una sesión de la base",
  escalate: "escalar",
};

function summarizeArgs(args: Record<string, unknown>) {
  return Object.entries(args)
    .filter(([, value]) => value !== null && value !== undefined && value !== "")
    .map(([key, value]) => `${key}=${typeof value === "string" ? value : JSON.stringify(value)}`)
    .join("  ")
    .slice(0, 140);
}

function Line({ event }: { event: AgentEvent }) {
  switch (event.type) {
    case "triage":
      return <p className="text-foreground">&gt; triage: comparé cada métrica con la hora anterior</p>;
    case "tool_call":
      return (
        <p className="mt-3 text-foreground">
          <span className="text-muted-foreground">ronda {event.round} </span>
          <span className="text-accent">{event.name}</span>
          <span className="text-muted-foreground"> {summarizeArgs(event.args)}</span>
        </p>
      );
    case "tool_result": {
      const lines = event.content.split("\n").filter(Boolean);
      return (
        <div className="border-l border-border pl-3 text-muted-foreground">
          {lines.slice(0, 3).map((line, i) => (
            <p key={i} className="truncate">
              {line}
            </p>
          ))}
          {lines.length > 3 && <p className="opacity-60">… {lines.length - 3} líneas más</p>}
        </div>
      );
    }
    case "llm_fallback":
      return (
        <p className="mt-3 text-accent">
          &gt; {event.model} no respondió; sigo con {event.fallback_to ?? "ningún respaldo"}
        </p>
      );
    case "diagnosis":
      return (
        <p className="mt-4 text-foreground">
          &gt; diagnóstico listo: {event.diagnosis.service} · {event.tokens.toLocaleString("es")} tokens
        </p>
      );
    case "awaiting_approval":
      return <p className="text-accent">&gt; espero tu aprobación para actuar</p>;
    case "approval":
      return (
        <p className="mt-3 text-foreground">
          &gt; {event.approved ? "aprobado" : "rechazado"} por {event.by}
          {event.note && <span className="text-muted-foreground"> ({event.note})</span>}
        </p>
      );
    case "execution":
      return (
        <p className={event.status === "executed" ? "text-foreground" : "text-destructive"}>
          &gt; {event.status === "executed" ? event.detail : `no se pudo ejecutar: ${event.detail}`}
        </p>
      );
    case "verification":
      if (event.skipped) return <p className="text-muted-foreground">&gt; sin verificación</p>;
      return (
        <p className={event.recovered ? "text-success" : "text-destructive"}>
          &gt; {event.recovered ? "la tienda volvió a la normalidad" : "el problema sigue"}
        </p>
      );
    case "error":
      return <p className="mt-3 text-destructive">&gt; la investigación falló: {event.error}</p>;
    default:
      return null;
  }
}

export function Terminal({ events, phase }: { events: AgentEvent[]; phase: Phase }) {
  const bottom = useRef<HTMLDivElement>(null);
  useEffect(() => bottom.current?.scrollIntoView({ block: "end" }), [events.length]);

  const working = phase === "investigating" || phase === "executing";
  return (
    <section aria-label="Investigación en vivo" className="flex min-h-0 flex-col border-2 border-foreground">
      <header className="flex items-center gap-2 border-b-2 border-foreground px-4 py-2">
        <span className={`h-2 w-2 ${working ? "bg-accent" : "bg-muted-foreground"}`} />
        <span className="h-2 w-2 bg-foreground" />
        <span className="h-2 w-2 border border-foreground" />
        <h2 className="ml-auto text-xs text-muted-foreground">investigación en vivo</h2>
      </header>
      <div
        className="dot-grid-bg min-h-[420px] flex-1 overflow-y-auto p-4 text-xs leading-relaxed"
        aria-live="polite"
      >
        {events.length === 0 ? (
          <p className="text-muted-foreground">
            Elegí un tipo de fallo y simulá un incidente: acá vas a ver cómo lo investiga el agente,
            paso a paso.
          </p>
        ) : (
          events.map((event, i) => <Line key={i} event={event} />)
        )}
        {working && <span className="animate-blink text-accent">_</span>}
        <div ref={bottom} />
      </div>
    </section>
  );
}

export function actionLabel(kind: string) {
  return ACTIONS[kind] ?? kind;
}
