import { prometheus } from "@/lib/backend";

// Lo que nota un cliente de la tienda, en los últimos 15 minutos.
const METRICS = [
  {
    key: "orders",
    label: "Pedidos por minuto",
    unit: "",
    query: 'sum(rate(orders_total{status="confirmed"}[1m])) * 60',
  },
  {
    key: "errors",
    label: "Pedidos con error",
    unit: "%",
    query:
      'sum(rate(http_requests_total{service="shop",status=~"5.."}[1m])) / sum(rate(http_requests_total{service="shop"}[1m])) * 100',
    max: 5,
  },
  {
    key: "latency",
    label: "Tiempo de respuesta",
    unit: "ms",
    query:
      'histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket{service="shop"}[1m]))) * 1000',
    max: 500,
  },
];

export async function GET() {
  const end = Math.floor(Date.now() / 1000);
  const start = end - 15 * 60;
  const metrics = await Promise.all(
    METRICS.map(async ({ query, ...metric }) => {
      const params = new URLSearchParams({ query, start: String(start), end: String(end), step: "15" });
      const body = await prometheus(`/api/v1/query_range?${params}`)
        .then((r) => r.json())
        .catch(() => null);
      const values: number[] = (body?.data?.result?.[0]?.values ?? [])
        .map(([, v]: [number, string]) => Number(v))
        .map((v: number) => (Number.isFinite(v) ? v : 0));
      const current = values.at(-1) ?? null;
      // Pedidos: mal si cayeron a menos del 60 % de lo habitual en la ventana.
      const typical = [...values].sort((a, b) => a - b)[Math.floor(values.length / 2)] ?? 0;
      const healthy =
        current === null
          ? null
          : "max" in metric
            ? current <= (metric.max as number)
            : typical === 0 || current >= typical * 0.6;
      return { ...metric, values, current, healthy };
    }),
  );
  return Response.json({ metrics });
}
