import asyncio
import json

import httpx
import pytest

from incilot_agent import triage
from incilot_agent.tools import _http


@pytest.mark.parametrize(
    ("recent", "baseline", "min_delta", "expected"),
    [
        (0.95, 0.01, 0.05, True),  # latency multiplied: the incident
        (0.004, 0.003, 0.02, False),  # noise: it rises, but very little in absolute terms
        (0.03, 0.01, 0.05, False),  # ×3 but less than the absolute minimum
        (0.5, 0.4, 0.05, False),  # it moved, but by less than double
        (0.0, 0.3, 0.1, True),  # dropped to zero
        (0.2, None, 0.1, True),  # did not exist before and is relevant now
        (0.01, None, 0.1, False),
    ],
)
def test_changed(recent, baseline, min_delta, expected):
    assert triage.changed(recent, baseline, min_delta) is expected


def test_log_patterns_are_classified_against_the_previous_hour(monkeypatch):
    now = 1_700_000_000 * 10**9
    monkeypatch.setattr(triage.time, "time_ns", lambda: now)

    def line(msg, exc):
        return json.dumps({"level": "error", "service": "users", "msg": msg, "exc": f"T\n{exc}"})

    minute = 60 * 10**9
    values = [
        [str(now - 30 * minute - i), line("unhandled error", "ConnectionResetError: x")]
        for i in range(40)
    ]
    values += [
        [str(now - 1 * minute - i), line("unhandled error", "ConnectionResetError: x")]
        for i in range(3)
    ]
    values += [
        [str(now - 2 * minute - i), line("unhandled error", "KeyError: 'trial'")] for i in range(20)
    ]

    def respond(request):
        body = {"data": {"result": [{"stream": {"service": "users"}, "values": values}]}}
        return httpx.Response(200, json=body)

    monkeypatch.setattr(
        _http,
        "client",
        lambda base_url: httpx.AsyncClient(
            base_url=base_url, transport=httpx.MockTransport(respond)
        ),
    )
    lines = asyncio.run(triage.log_changes())
    assert lines[0].startswith("NEW") and "KeyError" in lines[0]
    assert lines[1].startswith("stable") and "ConnectionResetError" in lines[1]
