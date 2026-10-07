"use client";

import { useEffect, useState } from "react";
import { actionLabel } from "@/components/incident/terminal";

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
  if (!p.approved) return { text: "rechazada", tone: "text-muted-foreground" };
  if (p.recovered) return { text: "resuelta", tone: "text-success" };
  return { text: "no se resolvió", tone: "text-destructive" };
}

/** Investigaciones anteriores. Al elegir una se reproduce entera. */
export function History({ refreshKey, onOpen }: { refreshKey: string; onOpen: (id: string) => void }) {
  const [items, setItems] = useState<Past[]>([]);

  useEffect(() => {
    fetch("/api/history")
      .then((r) => (r.ok ? r.json() : []))
      .then(setItems)
      .catch(() => {});
  }, [refreshKey]);

  return (
    <section aria-label="Investigaciones anteriores" className="flex min-h-[120px] flex-1 flex-col border-2 border-foreground p-4">
      <h2 className="shrink-0 text-sm text-foreground">Anteriores</h2>
      {items.length === 0 ? (
        <p className="mt-1 text-xs text-muted-foreground">Las investigaciones que termines van a aparecer acá.</p>
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
                    <span className="truncate text-foreground">{p.service ?? "sin diagnóstico"}</span>
                    <span className={`shrink-0 ${result.tone}`}>{result.text}</span>
                  </span>
                  <span className="mt-0.5 block truncate text-muted-foreground">
                    {new Date(p.recorded_at).toLocaleString("es", { dateStyle: "short", timeStyle: "short" })}
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
