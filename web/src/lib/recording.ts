// Plays a recorded investigation (web/public/replays, made with `make record`) as if it
// were happening now: the fault, the minute until the symptoms show, every step of the
// agent at its own pace (sped up), and the shop's health at each moment.
//
// Interactive: it stops where the agent asks for approval and the visitor decides.
// Approving plays what really happened next (the fix and the verification). Rejecting
// ends it there: nothing was applied, so there is nothing else to show.

import type { AgentEvent, Replay } from "@/lib/incident";

export const SPEED = 3;
// Long waits (the minute measuring the shop after the fix) are shortened further.
const MAX_GAP_MS = 5_000;
const MIN_GAP_MS = 350;
const TICK_MS = 500;

type Handlers = {
  /** The shop has just broken: the symptoms show in `ms` (sped up). */
  onBreak: (symptomsInMs: number) => void;
  onInvestigate: () => void;
  onEvent: (event: AgentEvent) => void;
  /** The recorded moment being shown (ms): the health charts follow it. */
  onClock: (at: number) => void;
};

export class Player {
  private timers: ReturnType<typeof setTimeout>[] = [];
  private ticker: ReturnType<typeof setInterval> | undefined;
  private next = 0; // index of the next event to show
  private clock: number;
  private readonly end: number; // the last recorded moment (the shop back to normal)
  private paused = false;

  private readonly recording: Replay;
  private readonly handlers: Handlers;
  private readonly interactive: boolean;

  constructor(recording: Replay, handlers: Handlers, interactive: boolean) {
    this.recording = recording;
    this.handlers = handlers;
    this.interactive = interactive;
    this.clock = recording.injectedAt;
    const lastEvent = recording.events.at(-1)?.at ?? recording.injectedAt;
    const lastMetric = Math.max(...Object.values(recording.health).map((s) => s.at(-1)?.[0] ?? 0));
    this.end = Math.max(lastEvent, lastMetric);
  }

  start() {
    const { injectedAt, events } = this.recording;
    const warmup = Math.max(0, ((events[0]?.at ?? injectedAt) - injectedAt) / SPEED);
    this.handlers.onBreak(warmup);
    this.handlers.onClock(this.clock);
    this.tick();
    this.timers.push(
      setTimeout(() => {
        this.handlers.onInvestigate();
        this.schedule();
      }, warmup),
    );
  }

  /** The visitor's decision, when the recording stopped for it. */
  decide(approved: boolean, note = "") {
    if (!this.paused) return;
    this.paused = false;
    if (approved) {
      this.tick();
      this.schedule();
      return;
    }
    this.stop();
    this.handlers.onEvent({ type: "approval", approved: false, by: "you", note: note || "rejected" });
    this.handlers.onEvent({ type: "done" });
  }

  /** Shows the rest at once (up to the decision, if it's still pending). */
  skip() {
    this.clearTimers();
    while (this.next < this.recording.events.length && !this.paused) this.show();
  }

  stop() {
    this.clearTimers();
    this.next = this.recording.events.length;
  }

  private schedule() {
    const { events } = this.recording;
    let delay = 0;
    let previous = this.clock;
    for (let i = this.next; i < events.length; i++) {
      delay += Math.max(MIN_GAP_MS, Math.min((events[i].at - previous) / SPEED, MAX_GAP_MS));
      previous = events[i].at;
      this.timers.push(setTimeout(() => this.show(), delay));
      if (this.interactive && events[i].type === "awaiting_approval") break;
    }
  }

  private show() {
    const event = this.recording.events[this.next++];
    if (!event) return;
    this.clock = Math.max(this.clock, event.at);
    this.handlers.onClock(this.clock);
    // The recorded approval stands for the visitor's: say so.
    this.handlers.onEvent(event.type === "approval" ? { ...event, by: "you", note: "approved" } : event);
    if (this.interactive && event.type === "awaiting_approval") {
      this.paused = true;
      this.clearTimers();
    }
  }

  /** Between events, the recorded clock keeps moving (sped up) so the charts do too. */
  private tick() {
    clearInterval(this.ticker);
    this.ticker = setInterval(() => {
      // Up to the next event; after the last one, on until the shop is back to normal.
      const upcoming = this.recording.events[this.next]?.at ?? this.end;
      this.clock = Math.min(this.clock + TICK_MS * SPEED, Math.max(upcoming, this.clock));
      this.handlers.onClock(this.clock);
      if (this.clock >= this.end) clearInterval(this.ticker);
    }, TICK_MS);
  }

  private clearTimers() {
    this.timers.forEach(clearTimeout);
    this.timers = [];
    clearInterval(this.ticker);
  }
}
