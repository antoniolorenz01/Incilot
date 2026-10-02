import json

import pytest
from fastapi.testclient import TestClient

from incilot_sim.common import faults
from incilot_sim.common.app import create_app
from incilot_sim.common.faults import Faults, switchboard

TRACEBACK = "Traceback (most recent call last):\n  File \"inventory.py\", line 42\nKeyError: 'sku'"


@pytest.fixture
def client():
    app = create_app("test")

    @app.get("/items/{item_id}")
    async def get_item(item_id: int):
        return {"id": item_id}

    yield TestClient(app)
    switchboard.apply(Faults())


def activate(**raw):
    switchboard.apply(Faults.parse({k: json.dumps(v) for k, v in raw.items()}))


def test_parse_ignores_unknown_fields():
    parsed = Faults.parse({"latency": '{"ms": 5}', "flags": '["a"]', "unknown": "{}"})
    assert parsed.latency == {"ms": 5}
    assert parsed.flags == frozenset({"a"})


def test_injected_errors_look_like_real_errors(client, caplog):
    activate(errors={"rate": 1, "traceback": TRACEBACK})
    response = client.get("/items/1")
    assert response.status_code == 500
    assert response.json() == {"detail": "internal_error"}
    record = next(r for r in caplog.records if r.getMessage() == "unhandled error")
    assert record.fields["exc"] == TRACEBACK


def test_injected_errors_keep_route_in_metrics(client):
    activate(errors={"rate": 1, "traceback": TRACEBACK})
    client.get("/items/2")
    metrics = client.get("/metrics").text
    assert 'http_requests_total{method="GET",route="/items/{item_id}",status="500"}' in metrics


def test_faults_never_affect_health_and_metrics(client):
    activate(errors={"rate": 1, "traceback": TRACEBACK}, rate_limit={"rps": 0})
    assert client.get("/health").status_code == 200
    assert client.get("/metrics").status_code == 200


def test_paths_limit_the_fault(client):
    activate(errors={"rate": 1, "traceback": TRACEBACK, "paths": ["/other"]})
    assert client.get("/items/1").status_code == 200


def test_rate_limit(client):
    activate(rate_limit={"rps": 2})
    statuses = [client.get("/items/1").status_code for _ in range(4)]
    assert statuses == [200, 200, 429, 429]


def test_memory_leak_is_released_when_deactivated(client):
    activate(memory_leak={"kb_per_request": 1})
    client.get("/items/1")
    assert switchboard._leaked_memory
    switchboard.apply(Faults())
    assert not switchboard._leaked_memory


def test_flags_and_overrides():
    activate(flags=["skip_reservation_release"], overrides={"decline_rate": 0.5})
    assert faults.flag("skip_reservation_release")
    assert not faults.flag("other")
    assert faults.override("decline_rate", 0.03) == 0.5
    assert faults.override("cache_ttl_seconds", 300) == 300
    switchboard.apply(Faults())
