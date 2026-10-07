"use client";

import { useEffect, useState } from "react";
import { CheckIcon, Loader2Icon } from "lucide-react";
import { type Phase, STEPS, stepOf } from "@/lib/incident";

/** Pasos del flujo: dónde está el usuario y qué sigue. */
export function Steps({ phase }: { phase: Phase }) {
  const current = stepOf(phase);
  const finished = phase === "done";
  return (
    <ol className="grid grid-cols-2 border-2 border-foreground text-xs md:grid-cols-4" aria-label="Pasos">
      {STEPS.map((step, i) => {
        const done = i < current || (finished && i === current);
        const active = i === current && !finished;
        return (
          <li
            key={step}
            aria-current={active ? "step" : undefined}
            className={`flex items-center gap-2 border-foreground px-3 py-2 not-last:border-r-2 max-md:nth-2:border-r-0 max-md:nth-[-n+2]:border-b-2 ${
              active ? "bg-accent text-accent-foreground" : done ? "text-foreground" : "text-muted-foreground"
            }`}
          >
            <span className="flex h-5 w-5 shrink-0 items-center justify-center border border-current">
              {done ? <CheckIcon className="h-3 w-3" /> : i + 1}
            </span>
            {step}
          </li>
        );
      })}
    </ol>
  );
}

function useNow(ticking: boolean) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!ticking) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [ticking]);
  return now;
}

const MESSAGES: Partial<Record<Phase, { title: string; detail: string }>> = {
  breaking: {
    title: "Rompiendo la tienda",
    detail: "Le inyectamos un fallo real. Esperamos a que aparezcan los síntomas antes de llamar al agente.",
  },
  investigating: {
    title: "El agente está investigando",
    detail: "Revisa métricas, logs, commits y la base de datos. Suele tardar entre 30 y 90 segundos.",
  },
  awaiting_approval: {
    title: "Tu turno: revisá el diagnóstico y decidí",
    detail: "El agente no toca nada sin tu aprobación. Podés aprobar su propuesta, corregirla o rechazarla.",
  },
  executing: {
    title: "Aplicando la solución y verificando",
    detail: "Después de actuar, esperamos un minuto y medimos si la tienda volvió a la normalidad.",
  },
};

/** Qué está pasando ahora, con indicador de carga y tiempo. */
export function Status({
  phase,
  countdownTo,
}: {
  phase: Phase;
  countdownTo?: number | null;
}) {
  // Se monta de nuevo en cada fase (key={phase}): `since` es el inicio de la fase.
  const [since] = useState(() => Date.now());
  const message = MESSAGES[phase];
  const waiting = Boolean(message) && phase !== "awaiting_approval";
  const now = useNow(waiting);
  if (!message) return null;

  const elapsed = Math.max(0, Math.round((now - since) / 1000));
  const remaining = countdownTo != null ? Math.max(0, Math.ceil((countdownTo - now) / 1000)) : null;
  return (
    <div
      role="status"
      aria-live="polite"
      className={`flex items-start gap-3 border-2 p-3 ${waiting ? "border-border" : "border-accent"}`}
    >
      {waiting ? (
        <Loader2Icon className="mt-0.5 h-4 w-4 shrink-0 animate-spin text-accent motion-reduce:animate-none" />
      ) : (
        <span className="mt-1 h-2.5 w-2.5 shrink-0 bg-accent" />
      )}
      <div className="flex-1 text-xs">
        <p className="text-sm text-foreground">{message.title}</p>
        <p className="mt-0.5 text-muted-foreground">{message.detail}</p>
        {phase === "breaking" && (
          // Qué pasa mientras esperamos, para alguien que no es técnico.
          <ol className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
            {[
              ["Aplicamos el fallo en la tienda", true],
              ["Los clientes empiezan a notarlo: mirá «Salud de la tienda»", remaining !== 0],
              ["Llega la alerta y el agente empieza a investigar", false],
            ].map(([text, current], i) => (
              <li key={i} className={i === 0 ? "text-foreground" : current ? "text-accent" : "text-muted-foreground"}>
                {i + 1}. {text}
                {i === 0 && " ✓"}
              </li>
            ))}
          </ol>
        )}
      </div>
      {waiting && (
        <p className="shrink-0 text-xs tabular-nums text-muted-foreground">
          {remaining !== null ? `faltan ${remaining} s` : `${elapsed} s`}
        </p>
      )}
    </div>
  );
}
