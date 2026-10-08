"""Shared Prometheus metrics. Prometheus adds the `service` label when scraping."""

from prometheus_client import Counter, Histogram

LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10)

HTTP_REQUESTS = Counter(
    "http_requests_total", "HTTP requests served", ["method", "route", "status"]
)
HTTP_LATENCY = Histogram(
    "http_request_duration_seconds",
    "Latency of HTTP requests served",
    ["method", "route"],
    buckets=LATENCY_BUCKETS,
)
UPSTREAM_REQUESTS = Counter(
    "upstream_requests_total", "Calls to other services", ["target", "status"]
)
UPSTREAM_LATENCY = Histogram(
    "upstream_request_duration_seconds",
    "Latency of calls to other services",
    ["target"],
    buckets=LATENCY_BUCKETS,
)
