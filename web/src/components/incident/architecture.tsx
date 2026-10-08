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

// An incident's journey, top to bottom. Each stage: what happens and with what.
const FLOW: { title: string; what: string; stack: string[] }[] = [
  {
    title: "The shop",
    what: "Four microservices with simulated traffic. An injector feeds them real faults and decoy commits.",
    stack: ["FastAPI", "Postgres", "Redis", "Docker Compose"],
  },
  {
    title: "Observability",
    what: "Metrics and logs from every service, as at any company.",
    stack: ["Prometheus", "Loki", "Alloy", "Grafana"],
  },
  {
    title: "Agent API",
    what: "Receives the alert, queues the investigation and runs it in a separate worker.",
    stack: ["FastAPI", "Redis queue", "worker async"],
  },
  {
    title: "The agent",
    what: "Triage without AI → loop of read-only tools (metrics, logs, git, RAG, SQL) → structured diagnosis → pause until a human decides.",
    stack: ["LangGraph", "OpenAI + fallback", "pgvector", "Postgres checkpoints"],
  },
  {
    title: "Action and verification",
    what: "Applies only what was approved, measures the shop again and records the incident.",
    stack: ["execution connectors", "Prometheus"],
  },
  {
    title: "This screen",
    what: "Receives each step live and resumes if the connection drops.",
    stack: ["Next.js 16", "React 19", "Redis Streams", "SSE", "Tailwind"],
  },
];

/** "How it's built": the architecture on one screen. */
export function Architecture() {
  return (
    <Dialog>
      <DialogTrigger render={<Button variant="outline" size="sm" />}>How it’s built</DialogTrigger>
      <DialogContent className="max-h-[90dvh] overflow-y-auto border-2 border-foreground sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>How it’s built</DialogTitle>
          <DialogDescription>
            An incident’s journey, from the moment the shop breaks until the fix is verified. On top of that, an eval
            suite measures how often the agent gets it right.
          </DialogDescription>
        </DialogHeader>
        <ol className="flex flex-col text-xs">
          {FLOW.map((stage, i) => (
            <li key={stage.title} className="flex flex-col items-stretch">
              {i > 0 && <ArrowDownIcon className="mx-auto my-1 h-4 w-4 text-muted-foreground" aria-hidden />}
              <div className="border-2 border-foreground p-3">
                <p className="text-sm text-foreground">{stage.title}</p>
                <p className="mt-1 leading-relaxed text-muted-foreground">{stage.what}</p>
                <ul className="mt-2 flex flex-wrap gap-1.5" aria-label="Tools">
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
