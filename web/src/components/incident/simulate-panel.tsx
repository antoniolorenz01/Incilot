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

type Catalog = Record<string, { title: string; category: string }>;

const CATEGORIES: Record<string, string> = {
  deploy: "Un deploy con un bug",
  config: "Un cambio de config",
  infra: "Infraestructura",
  external: "Un proveedor externo",
};

export function SimulatePanel({
  busy,
  onSimulate,
}: {
  busy: boolean;
  onSimulate: (scenario: string, dryRun: boolean) => void;
}) {
  const [catalog, setCatalog] = useState<Catalog>({});
  const [scenario, setScenario] = useState<string | null>(null);
  const [dryRun, setDryRun] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/scenarios")
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then(setCatalog)
      .catch(() => setError("No pude leer los tipos de fallo: ¿está levantado el entorno (make up)?"));
  }, []);

  const byCategory = Object.entries(catalog).reduce<Record<string, [string, string][]>>(
    (groups, [id, spec]) => {
      (groups[spec.category] ??= []).push([id, spec.title]);
      return groups;
    },
    {},
  );

  return (
    <section aria-label="Simular un incidente" className="flex flex-col gap-5 border-2 border-foreground p-4">
      <div>
        <h2 className="text-sm text-foreground">Simular un incidente</h2>
        <p className="mt-1 text-xs text-muted-foreground">
          Rompemos algo en la tienda de prueba. El agente no sabe qué fue.
        </p>
      </div>

      <label className="flex flex-col gap-2 text-xs text-muted-foreground">
        Tipo de fallo
        <Select value={scenario} onValueChange={(value) => setScenario(value as string)}>
          <SelectTrigger className="w-full min-w-0" aria-label="Tipo de fallo">
            <SelectValue placeholder="Elegí qué romper" className="truncate" />
          </SelectTrigger>
          {/* Más ancho que el botón: los nombres de los fallos son largos. */}
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
      </label>

      <label className="flex items-start gap-3 text-xs text-muted-foreground">
        <Switch checked={dryRun} onCheckedChange={setDryRun} className="mt-0.5" />
        <span>
          Modo prueba
          <span className="block opacity-70">Sin IA: recorre el flujo con un diagnóstico de ejemplo.</span>
        </span>
      </label>

      <Button
        disabled={!scenario || busy}
        onClick={() => scenario && onSimulate(scenario, dryRun)}
        className="bg-accent text-accent-foreground hover:bg-accent/85"
      >
        {busy ? "Incidente en curso" : "Simular incidente"}
      </Button>

      {error && <p className="text-xs text-destructive">{error}</p>}
    </section>
  );
}
