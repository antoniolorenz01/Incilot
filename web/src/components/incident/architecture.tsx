"use client";

import { ArrowDownIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";

// El recorrido de un incidente, de arriba abajo. Cada etapa: qué pasa y con qué.
const FLOW: { title: string; what: string; stack: string[] }[] = [
  {
    title: "La tienda",
    what: "Cuatro microservicios con tráfico simulado. Un inyector les mete fallos reales y commits señuelo.",
    stack: ["FastAPI", "Postgres", "Redis", "Docker Compose"],
  },
  {
    title: "Observabilidad",
    what: "Métricas y logs de cada servicio, como en cualquier empresa.",
    stack: ["Prometheus", "Loki", "Alloy", "Grafana"],
  },
  {
    title: "API del agente",
    what: "Recibe la alerta, encola la investigación y la corre en un worker aparte.",
    stack: ["FastAPI", "cola en Redis", "worker async"],
  },
  {
    title: "El agente",
    what: "Triage sin IA → bucle de herramientas de solo lectura (métricas, logs, git, RAG, SQL) → diagnóstico estructurado → pausa hasta que un humano decide.",
    stack: ["LangGraph", "OpenAI + respaldo", "pgvector", "checkpoints en Postgres"],
  },
  {
    title: "Acción y verificación",
    what: "Ejecuta solo lo aprobado, mide la tienda de nuevo y registra el incidente.",
    stack: ["conectores de ejecución", "Prometheus"],
  },
  {
    title: "Esta pantalla",
    what: "Recibe cada paso en vivo y retoma si se corta la conexión.",
    stack: ["Next.js 16", "React 19", "Redis Streams", "SSE", "Tailwind"],
  },
];

/** «Cómo está hecho»: la arquitectura en una pantalla. */
export function Architecture() {
  return (
    <Dialog>
      <DialogTrigger render={<Button variant="outline" size="sm" />}>Cómo está hecho</DialogTrigger>
      <DialogContent className="max-h-[90dvh] overflow-y-auto border-2 border-foreground sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>Cómo está hecho</DialogTitle>
          <DialogDescription>
            El camino de un incidente, desde que se rompe la tienda hasta que se verifica el arreglo. Además, una suite
            de evals mide qué tan seguido acierta el agente.
          </DialogDescription>
        </DialogHeader>
        <ol className="flex flex-col text-xs">
          {FLOW.map((stage, i) => (
            <li key={stage.title} className="flex flex-col items-stretch">
              {i > 0 && <ArrowDownIcon className="mx-auto my-1 h-4 w-4 text-muted-foreground" aria-hidden />}
              <div className="border-2 border-foreground p-3">
                <p className="text-sm text-foreground">{stage.title}</p>
                <p className="mt-1 leading-relaxed text-muted-foreground">{stage.what}</p>
                <ul className="mt-2 flex flex-wrap gap-1.5" aria-label="Herramientas">
                  {stage.stack.map((item) => (
                    <li key={item} className="border border-accent px-1.5 py-0.5 text-[11px] text-accent">
                      {item}
                    </li>
                  ))}
                </ul>
              </div>
            </li>
          ))}
        </ol>
      </DialogContent>
    </Dialog>
  );
}
