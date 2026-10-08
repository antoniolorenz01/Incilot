"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Section } from "@/components/incident/diagnosis-panel";
import { grade, type Investigation, type Truth } from "@/lib/incident";

/** Step 4: whether the shop recovered and whether the agent got it right. */
export function ResultPanel({
  investigation,
  truth,
  readOnly,
  onEnd,
}: {
  investigation: Investigation;
  truth: Truth | null;
  readOnly: boolean;
  onEnd: () => void;
}) {
  const [revealed, setRevealed] = useState(false);
  const { diagnosis, phase, verification, execution } = investigation;
  const result = truth && diagnosis ? grade(truth, diagnosis) : null;
  const finished = phase === "done" || phase === "error" || readOnly;

  if (!diagnosis && !finished) {
    return (
      <section
        aria-label="Outcome"
        className="shrink-0 border-2 border-dashed border-border p-4 text-xs text-muted-foreground"
      >
        Once you decide, you’ll see here whether the shop recovered and whether the agent got it right.
      </section>
    );
  }

  return (
    <section
      aria-label="Outcome"
      className="flex max-h-[65%] shrink-0 flex-col gap-3 overflow-y-auto border-2 border-foreground p-4 text-xs"
    >
      <h2 className="text-sm text-foreground">Outcome</h2>
      {phase === "awaiting_approval" && !readOnly && (
        <p className="text-muted-foreground">Waiting for your decision.</p>
      )}
      {(execution || verification || phase === "executing") && (
        <Section title="The shop" topic="verification">
          {phase === "executing" && !verification && (
            <p className="text-muted-foreground">Applying and measuring the shop for a minute…</p>
          )}
          {verification && !verification.skipped && (
            <>
              <p className={`font-pixel text-xl ${verification.recovered ? "text-success" : "text-destructive"}`}>
                {verification.recovered ? "Resolved" : "Still failing"}
              </p>
              <table className="mt-2 w-full">
                <tbody>
                  {verification.checks.map((check) => (
                    <tr key={check.name} className="border-b border-border last:border-none">
                      <td className="py-1 text-muted-foreground">{check.name}</td>
                      <td className="py-1 text-right tabular-nums text-foreground">{check.value}</td>
                      <td className={`py-1 pl-2 text-right ${check.ok ? "text-success" : "text-destructive"}`}>
                        {check.ok ? "ok" : `> ${check.max}`}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </Section>
      )}

      {result && truth && (
        <Section title="Did the agent get it right?" topic="evals">
          {diagnosis?.service === "dry-run" && (
            <p className="mb-2 text-muted-foreground">
              Dry run: the diagnosis is a fixed example, so it cannot be right. Switch dry run off to watch the agent
              really investigate.
            </p>
          )}
          {!revealed ? (
            <Button variant="outline" size="sm" onClick={() => setRevealed(true)}>
              Show the right answer
            </Button>
          ) : (
            <div className="flex flex-col gap-2">
              <p className="break-words text-muted-foreground">{truth.root_cause}</p>
              <ul className="flex flex-col gap-1">
                {[
                  ["Action that fixes the problem", result.action],
                  ["Service", result.service],
                  [truth.culprit_sha ? "Culprit commit" : "Blame no commit", result.commit],
                ].map(([label, ok]) => (
                  <li key={label as string} className="flex justify-between gap-2">
                    <span className="text-muted-foreground">{label}</span>
                    <span className={ok ? "text-success" : "text-destructive"}>{ok ? "right" : "wrong"}</span>
                  </li>
                ))}
              </ul>
              {result.decoy && <p className="text-destructive">It blamed an innocent commit (a decoy).</p>}
            </div>
          )}
        </Section>
      )}
      {finished && (
        <Button variant="ghost" size="sm" className="self-start" onClick={onEnd}>
          {readOnly ? "Back" : "End and simulate another"}
        </Button>
      )}
    </section>
  );
}
