"use client";

import { useEffect, useState } from "react";
import type { ReplayEntry } from "@/lib/incident";
import { RECORDED } from "@/lib/mode";
import { actionLabel } from "@/components/incident/terminal";
import { Explain } from "@/components/incident/explain";

type Past = {
  id: string;
  recorded_at: string;
  service: string | null;
  proposed: { kind: string; target: string } | null;
  executed: { kind: string; target: string } | null;
  approved: boolean | null;
  recovered: boolean | null;
};

function outcome(p: Past) {
  if (!p.approved) return { text: "rejected", tone: "text-muted-foreground" };
  if (p.recovered) return { text: "resolved", tone: "text-success" };
  return { text: "not resolved", tone: "text-destructive" };
}

const CATEGORY: Record<string, string> = {
  deploy: "deploy",
  config: "config",
  infra: "infrastructure",
  external: "external provider",
};

/** Recorded examples (played at their own pace) and past investigations (shown in full). */
export function History({
  refreshKey,
  onOpen,
  onReplay,
}: {
  refreshKey: string;
  onOpen: (id: string) => void;
  onReplay: (entry: ReplayEntry) => void;
}) {
  const [items, setItems] = useState<Past[]>([]);
  const [replays, setReplays] = useState<ReplayEntry[]>([]);

  useEffect(() => {
    if (RECORDED) return; // no backend: the recordings are the history
    fetch("/api/history")
      .then((r) => (r.ok ? r.json() : []))
      .then(setItems)
      .catch(() => {});
  }, [refreshKey]);

  useEffect(() => {
    fetch("/replays/index.json")
      .then((r) => (r.ok ? r.json() : []))
      .then(setReplays)
      .catch(() => {});
  }, []);

  return (
    <section
      aria-label="Past investigations"
      className="flex min-h-[120px] flex-1 flex-col border-2 border-foreground p-4"
    >
      {replays.length > 0 && (
        <div
          className={
            RECORDED
              ? "flex min-h-0 flex-1 flex-col"
              : "mb-3 flex max-h-44 shrink-0 flex-col border-b-2 border-border pb-3"
          }
        >
          <h2 className="flex shrink-0 items-center gap-1.5 text-sm text-foreground">
            Watch a recording <Explain topic="replays" />
          </h2>
          <ul className="mt-1 flex min-h-0 flex-col overflow-y-auto pr-1">
            {replays.map((replay) => (
              <li key={replay.file}>
                <button
                  onClick={() => onReplay(replay)}
                  className="flex w-full justify-between gap-2 py-1.5 text-left text-xs hover:bg-muted/50 focus-visible:outline-2 focus-visible:outline-ring"
                >
                  <span className="truncate text-foreground">
                    {replay.title}
                    <span className="text-muted-foreground"> · {replay.variant.replaceAll("-", " ")}</span>
                  </span>
                  <span className="shrink-0 text-muted-foreground">{CATEGORY[replay.category] ?? replay.category}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
      {!RECORDED && (
        <h2 className="flex shrink-0 items-center gap-1.5 text-sm text-foreground">
          Past investigations <Explain topic="history" />
        </h2>
      )}
      {RECORDED ? null : items.length === 0 ? (
        <p className="mt-1 text-xs text-muted-foreground">Investigations you finish will appear here.</p>
      ) : (
        <ul className="mt-2 flex min-h-0 flex-1 flex-col overflow-y-auto pr-1">
          {items.map((p) => {
            const result = outcome(p);
            const action = p.executed ?? p.proposed;
            return (
              <li key={p.id} className="border-t border-border first:border-none">
                <button
                  onClick={() => onOpen(p.id)}
                  className="w-full py-2 text-left text-xs hover:bg-muted/50 focus-visible:outline-2 focus-visible:outline-ring"
                >
                  <span className="flex justify-between gap-2">
                    <span className="truncate text-foreground">{p.service ?? "no diagnosis"}</span>
                    <span className={`shrink-0 ${result.tone}`}>{result.text}</span>
                  </span>
                  <span className="mt-0.5 block truncate text-muted-foreground">
                    {new Date(p.recorded_at).toLocaleString("en-GB", {
                      dateStyle: "short",
                      timeStyle: "short",
                    })}
                    {action && ` · ${actionLabel(action.kind)}`}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
