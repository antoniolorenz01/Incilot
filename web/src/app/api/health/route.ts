import { prometheus } from "@/lib/backend";
import { METRICS, WINDOW_MS, summarise } from "@/lib/health";

/** The "Shop health" charts, live: the last 15 minutes from Prometheus. */
export async function GET() {
  const end = Math.floor(Date.now() / 1000);
  const start = end - WINDOW_MS / 1000;
  const metrics = await Promise.all(
    METRICS.map(async (metric) => {
      const params = new URLSearchParams({ query: metric.query, start: String(start), end: String(end), step: "15" });
      const body = await prometheus(`/api/v1/query_range?${params}`)
        .then((r) => r.json())
        .catch(() => null);
      const values: number[] = (body?.data?.result?.[0]?.values ?? [])
        .map(([, v]: [number, string]) => Number(v))
        .map((v: number) => (Number.isFinite(v) ? v : 0));
      return summarise(metric, values);
    }),
  );
  return Response.json({ metrics });
}
