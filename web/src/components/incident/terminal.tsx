"use client";

import { useEffect, useRef } from "react";
import {
  BookOpenIcon,
  DatabaseIcon,
  FileCodeIcon,
  GitCommitHorizontalIcon,
  GitPullRequestIcon,
  LineChartIcon,
  ScrollTextIcon,
  type LucideIcon,
} from "lucide-react";
import type { AgentEvent, Phase } from "@/lib/incident";

const ACTIONS: Record<string, string> = {
  rollback: "revertir un deploy",
  revert_config: "revertir un cambio de config",
  restart: "reiniciar",
  terminate_session: "terminar una sesión de la base",
  escalate: "escalar",
};

export function actionLabel(kind: string) {
  return ACTIONS[kind] ?? kind;
}

/** Hashes de commit: 7 caracteres, como en git. */
export function shortTarget(target: string) {
  return /^[0-9a-f]{12,}$/i.test(target.trim()) ? target.trim().slice(0, 7) : target;
}

// Qué hace cada herramienta, en palabras de una persona, y sobre qué.
const TOOLS: Record<string, { icon: LucideIcon; label: string; subject: (a: Record<string, unknown>) => string }> = {
  query_metrics: { icon: LineChartIcon, label: "Consulta métricas", subject: () => "" },
  search_logs: {
    icon: ScrollTextIcon,
    label: "Busca en los logs",
    subject: (a) =>
      [a.service ?? "todos los servicios", a.level, a.contains && `«${a.contains}»`].filter(Boolean).join(" · "),
  },
  list_commits: {
    icon: GitPullRequestIcon,
    label: "Lista los cambios recientes",
    subject: (a) => (a.path ? String(a.path) : ""),
  },
  show_commit: {
    icon: GitCommitHorizontalIcon,
    label: "Revisa un cambio",
    subject: (a) => shortTarget(String(a.sha ?? "")),
  },
  read_file: { icon: FileCodeIcon, label: "Lee un archivo", subject: (a) => String(a.path ?? "") },
  search_knowledge: {
    icon: BookOpenIcon,
    label: "Busca en la documentación",
    subject: (a) => `«${a.query ?? ""}»`,
  },
  query_database: { icon: DatabaseIcon, label: "Consulta la base de datos", subject: (a) => String(a.database ?? "") },
};

type Call = Extract<AgentEvent, { type: "tool_call" }>;
type Result = Extract<AgentEvent, { type: "tool_result" }>;
type RoundBlock = { kind: "round"; round: number; items: { call: Call; result?: Result }[] };
type Block = RoundBlock | { kind: "event"; event: AgentEvent };

/** Agrupa las herramientas por paso y empareja cada una con su resultado (llegan en orden). */
function toBlocks(events: AgentEvent[]): Block[] {
  const blocks: Block[] = [];
  let pending: RoundBlock["items"] = [];
  for (const event of events) {
    if (event.type === "tool_call") {
      const last = blocks.at(-1);
      if (last?.kind === "round" && last.round === event.round) last.items.push({ call: event });
      else blocks.push({ kind: "round", round: event.round, items: [{ call: event }] });
      pending = (blocks.at(-1) as RoundBlock).items;
    } else if (event.type === "tool_result") {
      const slot = pending.find((item) => !item.result);
      if (slot) slot.result = event;
    } else {
      blocks.push({ kind: "event", event });
    }
  }
  return blocks;
}

function summary(content: string) {
  const first = content.split("\n").find((line) => line.trim()) ?? "";
  return first.replace(/:$/, "");
}

function Round({ round, items }: RoundBlock) {
  return (
    <div className="mt-4 first:mt-0">
      <p className="mb-2 text-foreground">
        <span className="bg-foreground px-1.5 text-background">Paso {round}</span>
        <span className="ml-2 text-muted-foreground">
          {items.length} {items.length === 1 ? "consulta" : "consultas"}
        </span>
      </p>
      <ul className="flex flex-col gap-1.5 border-l border-border pl-3">
        {items.map(({ call, result }, i) => {
          const tool = TOOLS[call.name];
          const Icon = tool?.icon ?? LineChartIcon;
          const subject = tool?.subject(call.args) ?? "";
          const failed = result?.content.startsWith("error:");
          return (
            <li key={i}>
              <details>
                <summary className="flex cursor-pointer list-none items-start gap-2 [&::-webkit-details-marker]:hidden">
                  <Icon className="mt-0.5 h-3.5 w-3.5 shrink-0 text-accent" aria-hidden />
                  <span className="min-w-0 flex-1">
                    <span className="text-foreground">{tool?.label ?? call.name}</span>
                    {subject && <span className="text-muted-foreground"> · {subject}</span>}
                    <span className={`block truncate ${failed ? "text-destructive" : "text-muted-foreground opacity-80"}`}>
                      {result ? `→ ${summary(result.content)}` : "→ …"}
                    </span>
                  </span>
                </summary>
                <pre className="mt-1 mb-2 max-h-48 overflow-auto whitespace-pre-wrap break-words bg-muted/40 p-2 text-[11px] text-muted-foreground">
                  {JSON.stringify(call.args, null, 1)}
                  {"\n\n"}
                  {result?.content.slice(0, 3000) ?? "esperando resultado…"}
                </pre>
              </details>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function EventLine({ event }: { event: AgentEvent }) {
  switch (event.type) {
    case "triage":
      return <p className="mb-3 text-foreground">&gt; Comparó cada indicador de la tienda con la hora anterior</p>;
    case "llm_fallback":
      return (
        <p className="mt-3 text-accent">
          &gt; El modelo {event.model} no respondió; sigue con {event.fallback_to ?? "ningún respaldo"}
        </p>
      );
    case "diagnosis":
      return (
        <p className="mt-4 text-foreground">
          &gt; Diagnóstico listo: {event.diagnosis.service}
          <span className="text-muted-foreground"> · {event.tokens.toLocaleString("es")} tokens</span>
        </p>
      );
    case "awaiting_approval":
      return <p className="text-accent">&gt; Espera tu aprobación para actuar</p>;
    case "approval":
      return (
        <p className="mt-3 text-foreground">
          &gt; {event.approved ? "Aprobado" : "Rechazado"}
          {event.note && <span className="text-muted-foreground"> ({event.note})</span>}
        </p>
      );
    case "execution":
      return (
        <p className={event.status === "executed" ? "text-foreground" : "text-destructive"}>
          &gt; {event.status === "executed" ? event.detail : `No se pudo ejecutar: ${event.detail}`}
        </p>
      );
    case "verification":
      if (event.skipped) return <p className="text-muted-foreground">&gt; Sin verificación</p>;
      return (
        <p className={event.recovered ? "text-success" : "text-destructive"}>
          &gt; {event.recovered ? "La tienda volvió a la normalidad" : "El problema sigue"}
        </p>
      );
    case "error":
      return <p className="mt-3 text-destructive">&gt; La investigación falló: {event.error}</p>;
    default:
      return null;
  }
}

export function Terminal({ events, phase }: { events: AgentEvent[]; phase: Phase }) {
  const scroller = useRef<HTMLDivElement>(null);
  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight });
  }, [events.length]);

  const working = phase === "investigating" || phase === "executing";
  return (
    <section aria-label="Investigación en vivo" className="flex min-h-0 flex-col border-2 border-foreground">
      <header className="flex shrink-0 items-center gap-2 border-b-2 border-foreground px-4 py-2">
        <span className={`h-2 w-2 ${working ? "bg-accent" : "bg-muted-foreground"}`} />
        <span className="h-2 w-2 bg-foreground" />
        <span className="h-2 w-2 border border-foreground" />
        <h2 className="ml-auto truncate text-xs text-muted-foreground">
          investigación en vivo · tocá una consulta para ver el detalle
        </h2>
      </header>
      <div
        ref={scroller}
        className="dot-grid-bg min-h-0 flex-1 overflow-y-auto p-4 text-xs leading-relaxed"
        aria-live="polite"
      >
        {events.length === 0 && phase === "idle" ? (
          <div className="max-w-[60ch] space-y-3 text-muted-foreground">
            <p className="text-foreground">Cómo funciona</p>
            <ol className="list-decimal space-y-1.5 pl-4">
              <li>Elegí un tipo de fallo y apretá «Simular incidente»: rompemos algo de verdad en una tienda de prueba.</li>
              <li>El agente investiga solo, sin saber qué rompimos. Acá ves cada paso que da.</li>
              <li>Te propone una solución. No hace nada hasta que vos la aprobás.</li>
              <li>Si aprobás, la aplica y verifica que la tienda se recuperó. Al final podés ver si acertó.</li>
            </ol>
          </div>
        ) : events.length === 0 ? (
          <p className="text-muted-foreground">&gt; Esperando el primer paso del agente…</p>
        ) : (
          toBlocks(events).map((block, i) =>
            block.kind === "round" ? <Round key={i} {...block} /> : <EventLine key={i} event={block.event} />,
          )
        )}
        {working && <span className="animate-blink text-accent">_</span>}
      </div>
    </section>
  );
}
