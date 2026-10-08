"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Explain } from "@/components/incident/explain";
import { useDragScroll } from "@/lib/use-drag-scroll";

type Catalog = Record<string, { title: string; category: string }>;

const CATEGORIES: Record<string, string> = {
  deploy: "A deploy with a bug",
  config: "A config change",
  infra: "Infrastructure",
  external: "An external provider",
};

export function SimulatePanel({
  busy,
  runsLeft,
  onSimulate,
  onCancel,
}: {
  busy: boolean;
  /** Real investigations left today on the public demo (null: no limit). */
  runsLeft: number | null;
  onSimulate: (scenario: string, dryRun: boolean) => void;
  /** Only whoever started the simulation can cancel it. */
  onCancel?: () => void;
}) {
  const [catalog, setCatalog] = useState<Catalog>({});
  const [scenario, setScenario] = useState<string | null>(null);
  const [dryRun, setDryRun] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const scroller = useDragScroll<HTMLElement>();

  useEffect(() => {
    fetch("/api/scenarios")
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then(setCatalog)
      .catch(() => setError("Couldn't load the fault types: is the environment running (make up)?"));
  }, []);

  const byCategory = Object.entries(catalog).reduce<Record<string, [string, string][]>>((groups, [id, spec]) => {
    (groups[spec.category] ??= []).push([id, spec.title]);
    return groups;
  }, {});

  return (
    <section
      ref={scroller}
      aria-label="Simulate an incident"
      className="scroll-hidden flex min-h-0 shrink flex-col gap-4 overflow-y-auto border-2 border-foreground p-4"
    >
      <div>
        <h2 className="flex items-center gap-1.5 text-sm text-foreground">
          Simulate an incident <Explain topic="simulate" />
        </h2>
        <p className="mt-1 text-xs text-muted-foreground">
          We break something in the test shop. The agent doesn’t know what.
        </p>
      </div>

      {/* A div, not a label: the help icon is a button and would take the text's click. */}
      <div className="flex flex-col gap-2 text-xs text-muted-foreground">
        <span className="flex items-center gap-1.5">
          Fault type <Explain topic="scenario" />
        </span>
        {/* items: the text to show for each value (otherwise the technical id shows) */}
        <Select
          value={scenario}
          onValueChange={(value) => setScenario(value as string)}
          items={Object.fromEntries(Object.entries(catalog).map(([id, spec]) => [id, spec.title]))}
        >
          <SelectTrigger className="w-full min-w-0" aria-label="Fault type">
            <SelectValue placeholder="Pick what to break" className="truncate" />
          </SelectTrigger>
          {/* Wider than the button: fault names are long. */}
          <SelectContent className="w-auto min-w-(--anchor-width) max-w-[min(26rem,90vw)]">
            {Object.entries(byCategory).map(([category, items]) => (
              <SelectGroup key={category}>
                <SelectLabel>{CATEGORIES[category] ?? category}</SelectLabel>
                {items.map(([id, title]) => (
                  <SelectItem key={id} value={id}>
                    {title}
                  </SelectItem>
                ))}
              </SelectGroup>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="flex items-start gap-1.5">
        <label className="flex flex-1 items-start gap-3 text-xs text-muted-foreground">
          <Switch checked={dryRun} onCheckedChange={setDryRun} className="mt-0.5" />
          <span>
            Dry run
            <span className="block opacity-70">No AI: walks through the flow with an example diagnosis.</span>
          </span>
        </label>
        <Explain topic="dry_run" className="mt-0.5" />
      </div>

      <Button
        disabled={!scenario || busy}
        onClick={() => scenario && onSimulate(scenario, dryRun)}
        className="bg-accent text-accent-foreground hover:bg-accent/85"
      >
        {busy ? "Incident in progress" : "Simulate incident"}
      </Button>
      {busy && onCancel && (
        <Button variant="destructive" size="sm" onClick={onCancel}>
          Cancel simulation
        </Button>
      )}
      {runsLeft !== null && !busy && (
        <p className="text-xs text-muted-foreground">
          {runsLeft > 0
            ? `Real investigations left for you today: ${runsLeft}. Dry runs are unlimited.`
            : "No real investigations left for you today: dry runs and past investigations still work."}
        </p>
      )}

      {error && <p className="text-xs text-destructive">{error}</p>}
    </section>
  );
}
