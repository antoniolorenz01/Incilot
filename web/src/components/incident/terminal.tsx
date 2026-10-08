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
import { Explain, useTechMode } from "@/components/incident/explain";
import type { TopicId } from "@/lib/explain";
import type { AgentEvent, Phase } from "@/lib/incident";

const ACTIONS: Record<string, string> = {
  rollback: "roll back a deploy",
  revert_config: "revert a config change",
  restart: "restart",
  terminate_session: "end a database session",
  escalate: "escalate",
};

export function actionLabel(kind: string) {
  return ACTIONS[kind] ?? kind;
}

/** Commit hashes: 7 characters, as in git. */
export function shortTarget(target: string) {
  return /^[0-9a-f]{12,}$/i.test(target.trim()) ? target.trim().slice(0, 7) : target;
}

// What each tool does in plain words, what it acts on, and its explanation.
type Tool = {
  icon: LucideIcon;
  label: string;
  topic: TopicId;
  subject: (a: Record<string, unknown>) => string;
};
const TOOLS: Record<string, Tool> = {
  query_metrics: {
    icon: LineChartIcon,
    label: "Queries metrics",
    topic: "query_metrics",
    subject: () => "",
  },
  search_logs: {
    icon: ScrollTextIcon,
    topic: "search_logs",
    label: "Searches the logs",
    subject: (a) => [a.service ?? "all services", a.level, a.contains && `‘${a.contains}’`].filter(Boolean).join(" · "),
  },
  list_commits: {
    icon: GitPullRequestIcon,
    topic: "git",
    label: "Lists recent changes",
    subject: (a) => (a.path ? String(a.path) : ""),
  },
  show_commit: {
    icon: GitCommitHorizontalIcon,
    topic: "git",
    label: "Reviews a change",
    subject: (a) => shortTarget(String(a.sha ?? "")),
  },
  read_file: {
    icon: FileCodeIcon,
    label: "Reads a file",
    topic: "git",
    subject: (a) => String(a.path ?? ""),
  },
  search_knowledge: {
    icon: BookOpenIcon,
    topic: "rag",
    label: "Searches the documentation",
    subject: (a) => `‘${a.query ?? ""}’`,
  },
  query_database: {
    icon: DatabaseIcon,
    label: "Queries the database",
    topic: "query_database",
    subject: (a) => String(a.database ?? ""),
  },
};

type Call = Extract<AgentEvent, { type: "tool_call" }>;
type Result = Extract<AgentEvent, { type: "tool_result" }>;
type RoundBlock = {
  kind: "round";
  round: number;
  items: { call: Call; result?: Result }[];
};
type Block = RoundBlock | { kind: "event"; event: AgentEvent };

/** Groups tool calls by step and pairs each with its result (they arrive in order). */
function toBlocks(events: AgentEvent[]): Block[] {
  const blocks: Block[] = [];
  let pending: RoundBlock["items"] = [];
  for (const event of events) {
    if (event.type === "tool_call") {
      const last = blocks.at(-1);
      if (last?.kind === "round" && last.round === event.round) last.items.push({ call: event });
      else
        blocks.push({
          kind: "round",
          round: event.round,
          items: [{ call: event }],
        });
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

/** Seconds between two events, if both have a time. */
function seconds(from?: number, to?: number) {
  return from && to ? `${((to - from) / 1000).toFixed(1)} s` : null;
}

function Round({ round, items }: RoundBlock) {
  const tech = useTechMode();
  const took = seconds(items[0]?.call.at, items.at(-1)?.result?.at);
  return (
    <div className="mt-4 first:mt-0">
      <p className="mb-2 text-foreground">
        <span className="bg-foreground px-1.5 text-background">Step {round}</span>
        <span className="ml-2 text-muted-foreground">
          {items.length} {items.length === 1 ? "query" : "queries"}
          {tech && took && ` · ${took}`}
        </span>
      </p>
      <ul className="flex flex-col gap-1.5 border-l border-border pl-3">
        {items.map(({ call, result }, i) => {
          const tool = TOOLS[call.name];
          const Icon = tool?.icon ?? LineChartIcon;
          const subject = tool?.subject(call.args) ?? "";
          const failed = result?.content.startsWith("error:");
          return (
            <li key={i} className="flex items-start gap-2">
              <details className="min-w-0 flex-1">
                <summary className="flex cursor-pointer list-none items-start gap-2 [&::-webkit-details-marker]:hidden">
                  <Icon className="mt-0.5 h-3.5 w-3.5 shrink-0 text-accent" aria-hidden />
                  <span className="min-w-0 flex-1">
                    <span className="text-foreground">{tool?.label ?? call.name}</span>
                    {subject && <span className="text-muted-foreground"> · {subject}</span>}
                    {tech && (
                      <span className="block text-[11px] text-accent/80">
                        {call.name}()
                        {seconds(call.at, result?.at) && ` · ${seconds(call.at, result?.at)}`}
                      </span>
                    )}
                    <span
                      className={`block truncate ${failed ? "text-destructive" : "text-muted-foreground opacity-80"}`}
                    >
                      {result ? `→ ${summary(result.content)}` : "→ …"}
                    </span>
                  </span>
                </summary>
                <pre className="mt-1 mb-2 max-h-48 overflow-auto whitespace-pre-wrap break-words bg-muted/40 p-2 text-[11px] text-muted-foreground">
                  {JSON.stringify(call.args, null, 1)}
                  {"\n\n"}
                  {result?.content.slice(0, 3000) ?? "waiting for the result…"}
                </pre>
              </details>
              {tool && <Explain topic={tool.topic} className="mt-0.5" />}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function EventLine({ event }: { event: AgentEvent }) {
  const tech = useTechMode();
  switch (event.type) {
    case "triage":
      return (
        <p className="mb-3 flex items-center gap-2 text-foreground">
          &gt; Compared every shop indicator with the previous hour <Explain topic="triage" />
        </p>
      );
    case "llm_fallback":
      return (
        <p className="mt-3 text-accent">
          &gt; Model {event.model} did not respond; carrying on with {event.fallback_to ?? "no fallback"}
        </p>
      );
    case "diagnosis":
      return (
        <p className="mt-4 text-foreground">
          &gt; Diagnosis ready: {event.diagnosis.service}
          <span className="text-muted-foreground">
            {" "}
            · {event.tokens.toLocaleString("en-GB")} tokens
            {tech && ` · stop: ${event.stop_reason}`}
          </span>
        </p>
      );
    case "awaiting_approval":
      return <p className="text-accent">&gt; Waiting for your approval to act</p>;
    case "approval":
      return (
        <p className="mt-3 text-foreground">
          &gt; {event.approved ? "Approved" : "Rejected"}
          {event.note && <span className="text-muted-foreground"> ({event.note})</span>}
        </p>
      );
    case "execution":
      return (
        <p className={event.status === "executed" ? "text-foreground" : "text-destructive"}>
          &gt; {event.status === "executed" ? event.detail : `Could not apply: ${event.detail}`}
        </p>
      );
    case "verification":
      if (event.skipped) return <p className="text-muted-foreground">&gt; No verification</p>;
      return (
        <p className={event.recovered ? "text-success" : "text-destructive"}>
          &gt; {event.recovered ? "The shop is back to normal" : "The problem persists"}
        </p>
      );
    case "error":
      return <p className="mt-3 text-destructive">&gt; The investigation failed: {event.error}</p>;
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
    <section aria-label="Live investigation" className="flex min-h-0 flex-col border-2 border-foreground">
      <header className="flex shrink-0 items-center gap-2 border-b-2 border-foreground px-4 py-2">
        <span className={`h-2 w-2 ${working ? "bg-accent" : "bg-muted-foreground"}`} />
        <span className="h-2 w-2 bg-foreground" />
        <span className="h-2 w-2 border border-foreground" />
        <h2 className="ml-2 flex min-w-0 items-center gap-1.5 text-xs text-foreground">
          The agent <Explain topic="agent" />
        </h2>
        <p className="ml-auto flex min-w-0 items-center gap-1.5 text-xs text-muted-foreground">
          <span className="truncate">live · click a query to see the details</span>
          <Explain topic="stream" />
        </p>
      </header>
      <div
        ref={scroller}
        className="dot-grid-bg min-h-0 flex-1 overflow-y-auto p-4 text-xs leading-relaxed"
        aria-live="polite"
      >
        {events.length === 0 && phase === "idle" ? (
          <div className="max-w-[60ch] space-y-3 text-muted-foreground">
            <p className="text-foreground">How it works</p>
            <ol className="list-decimal space-y-1.5 pl-4">
              <li>Pick a fault type and press ‘Simulate incident’: we really break something in a test shop.</li>
              <li>
                The agent investigates on its own, without knowing what we broke. You see every step it takes here.
              </li>
              <li>It proposes a fix. It does nothing until you approve it.</li>
              <li>
                If you approve, it applies the fix and checks the shop has recovered. At the end you can see whether it
                got it right.
              </li>
            </ol>
          </div>
        ) : events.length === 0 ? (
          <p className="text-muted-foreground">&gt; Waiting for the agent’s first step…</p>
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
