// The "Shop health" charts: what a customer notices. Shared by the live route
// (/api/health, from Prometheus) and the recorded demo (from the saved series).

export type HealthMetric = {
  key: string;
  label: string;
  unit: string;
  values: number[];
  current: number | null;
  healthy: boolean | null;
};

export const WINDOW_MS = 15 * 60_000;

export const METRICS = [
  {
    key: "orders",
    label: "Orders per minute",
    unit: "",
    query: 'sum(rate(orders_total{status="confirmed"}[1m])) * 60',
  },
  {
    key: "errors",
    label: "Failed orders",
    unit: "%",
    query:
      'sum(rate(http_requests_total{service="shop",status=~"5.."}[1m])) / sum(rate(http_requests_total{service="shop"}[1m])) * 100',
    max: 5,
  },
  {
    key: "latency",
    label: "Response time",
    unit: "ms",
    query:
      'histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket{service="shop"}[1m]))) * 1000',
    max: 500,
  },
] as const;

/** A chart from its values: the current one and whether it looks healthy. */
export function summarise(metric: (typeof METRICS)[number], values: number[]): HealthMetric {
  const current = values.at(-1) ?? null;
  // Orders: unhealthy if they fell below 60 % of the window's typical rate.
  const typical = [...values].sort((a, b) => a - b)[Math.floor(values.length / 2)] ?? 0;
  const healthy =
    current === null ? null : "max" in metric ? current <= metric.max : typical === 0 || current >= typical * 0.6;
  return { key: metric.key, label: metric.label, unit: metric.unit, values, current, healthy };
}

/** The charts at a recorded moment: the 15 minutes before `at`. */
export function recordedHealth(series: Record<string, [number, number][]>, at: number): HealthMetric[] {
  return METRICS.map((metric) =>
    summarise(
      metric,
      (series[metric.key] ?? []).filter(([t]) => t > at - WINDOW_MS && t <= at).map(([, v]) => v),
    ),
  );
}
