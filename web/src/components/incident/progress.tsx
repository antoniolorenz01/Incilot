"use client";

import { useEffect, useState } from "react";
import { CheckIcon, Loader2Icon } from "lucide-react";
import { type Phase, STEPS, stepOf } from "@/lib/incident";

/** Screen columns: one per step, aligned with the steps bar. */
export const COLUMNS = "xl:grid-cols-[270px_minmax(0,1fr)_360px_310px]";

/** The flow's steps: where the user is and what comes next. On wide screens each
 * step sits above its column. */
export function Steps({ phase, hint }: { phase: Phase; hint?: string }) {
  const current = stepOf(phase);
  // Where to show "what to look at": the current step, or the first one before starting.
  const hintAt = Math.max(current, 0);
  const finished = phase === "done";
  return (
    <ol
      className={`grid grid-cols-2 border-2 border-foreground text-xs md:grid-cols-4 xl:gap-3 xl:border-0 ${COLUMNS}`}
      aria-label="Steps"
    >
      {STEPS.map((step, i) => {
        const done = i < current || (finished && i === current);
        const active = i === current && !finished;
        return (
          <li
            key={step}
            aria-current={active ? "step" : undefined}
            className={`flex flex-wrap items-center gap-x-2 gap-y-0.5 border-foreground px-3 py-2 not-last:border-r-2 xl:border-2 max-md:nth-2:border-r-0 max-md:nth-[-n+2]:border-b-2 ${
              active ? "bg-accent text-accent-foreground" : done ? "text-foreground" : "text-muted-foreground"
            }`}
          >
            <span className="flex h-5 w-5 shrink-0 items-center justify-center border border-current">
              {done ? <CheckIcon className="h-3 w-3" /> : i + 1}
            </span>
            {step}
            {hint && i === hintAt && (
              <span className={`basis-full pl-7 text-[11px] ${active ? "opacity-85" : "text-accent"}`}>{hint}</span>
            )}
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
    title: "Breaking the shop",
    detail: "We inject a real fault, then wait for the symptoms to show before calling the agent.",
  },
  investigating: {
    title: "The agent is investigating",
    detail: "It checks metrics, logs, commits and the database. It usually takes 30 to 90 seconds.",
  },
  awaiting_approval: {
    title: "Your turn: review the diagnosis and decide",
    detail: "The agent touches nothing without your approval. You can approve its proposal, amend it or reject it.",
  },
  executing: {
    title: "Applying the fix and verifying",
    detail: "After acting, we wait a minute and measure whether the shop is back to normal.",
  },
};

/** What is happening now, with a loading indicator and timer. */
export function Status({ phase, countdownTo }: { phase: Phase; countdownTo?: number | null }) {
  // Remounted on every phase (key={phase}): `since` is when the phase started.
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
          // What happens while we wait, for someone non-technical.
          <ol className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
            {[
              ["We apply the fault to the shop", true],
              ["Customers start to notice: watch ‘Shop health’", remaining !== 0],
              ["The alert fires and the agent starts investigating", false],
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
          {remaining !== null ? `${remaining} s left` : `${elapsed} s`}
        </p>
      )}
    </div>
  );
}
