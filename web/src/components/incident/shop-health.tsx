"use client";

import { useEffect, useState } from "react";
import { AlertTriangleIcon, CheckIcon } from "lucide-react";

type Metric = {
  key: string;
  label: string;
  unit: string;
  values: number[];
  current: number | null;
  healthy: boolean | null;
};

const REFRESH_MS = 10_000;

/** Línea de 2 px con los últimos 15 minutos. Una sola serie: sin leyenda. Se estira
 * al alto disponible para que la columna llene la pantalla como las demás. */
function Sparkline({ values, label }: { values: number[]; label: string }) {
  if (values.length < 2) return <div className="h-6" />;
  const width = 120;
  const height = 32;
  const max = Math.max(...values, 1e-9);
  const points = values
    .map((v, i) => `${(i / (values.length - 1)) * width},${height - 2 - (v / max) * (height - 4)}`)
    .join(" ");
  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      className="h-full w-full"
      role="img" aria-label={`${label}, últimos 15 minutos`}>
      <polyline points={points} fill="none" stroke="currentColor" strokeWidth={2} strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

function format(value: number | null, unit: string) {
  if (value === null) return "—";
  const digits = unit === "%" || value < 10 ? 1 : 0;
  return `${value.toFixed(digits)}${unit ? ` ${unit}` : ""}`;
}

/** Lo que nota un cliente: se ve la tienda romperse y volver a la normalidad. */
export function ShopHealth() {
  const [metrics, setMetrics] = useState<Metric[]>([]);

  useEffect(() => {
    let cancelled = false;
    const load = () =>
      fetch("/api/health")
        .then((r) => (r.ok ? r.json() : null))
        .then((body) => !cancelled && body && setMetrics(body.metrics))
        .catch(() => {});
    load();
    const timer = setInterval(load, REFRESH_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  return (
    <section aria-label="Salud de la tienda" className="flex min-h-0 flex-1 flex-col border-2 border-foreground p-4">
      <h2 className="text-sm text-foreground">Salud de la tienda</h2>
      <p className="mt-1 text-xs text-muted-foreground">Lo que notan los clientes, en vivo.</p>
      <div className="mt-2 flex min-h-0 flex-1 flex-col gap-3">
        {metrics.map((m) => (
          <div key={m.key} className="flex min-h-0 flex-1 flex-col border-t border-border pt-2">
            <div className="flex items-baseline justify-between gap-2 text-xs">
              <span className="text-muted-foreground">{m.label}</span>
              <span className="tabular-nums text-foreground">{format(m.current, m.unit)}</span>
            </div>
            <div className="my-1 grid min-h-6 flex-1 text-foreground/70">
              <Sparkline values={m.values} label={m.label} />
            </div>
            {m.healthy !== null && (
              <p className={`flex items-center gap-1 text-[11px] ${m.healthy ? "text-success" : "text-destructive"}`}>
                {m.healthy ? <CheckIcon className="h-3 w-3" /> : <AlertTriangleIcon className="h-3 w-3" />}
                {m.healthy ? "normal" : "con problemas"}
              </p>
            )}
          </div>
        ))}
        {metrics.length === 0 && <p className="text-xs text-muted-foreground">Cargando…</p>}
      </div>
    </section>
  );
}
