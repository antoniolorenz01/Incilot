"""Métricas Prometheus comunes. La etiqueta `service` la pone Prometheus al scrapear."""

from prometheus_client import Counter, Histogram

LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10)

HTTP_REQUESTS = Counter(
    "http_requests_total", "Requests HTTP atendidas", ["method", "route", "status"]
)
HTTP_LATENCY = Histogram(
    "http_request_duration_seconds",
    "Latencia de requests HTTP atendidas",
    ["method", "route"],
    buckets=LATENCY_BUCKETS,
)
UPSTREAM_REQUESTS = Counter(
    "upstream_requests_total", "Llamadas a otros servicios", ["target", "status"]
)
UPSTREAM_LATENCY = Histogram(
    "upstream_request_duration_seconds",
    "Latencia de llamadas a otros servicios",
    ["target"],
    buckets=LATENCY_BUCKETS,
)
