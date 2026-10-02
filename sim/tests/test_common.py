import json
import logging

import pytest
from fastapi.testclient import TestClient

from incilot_sim.common.app import create_app
from incilot_sim.common.log import JsonFormatter, get_logger, request_id


@pytest.fixture
def client():
    app = create_app("test")

    @app.get("/items/{item_id}")
    async def get_item(item_id: int):
        get_logger("test").info("item read", item_id=item_id)
        return {"id": item_id}

    @app.get("/boom")
    async def boom():
        raise RuntimeError("boom")

    return TestClient(app)


def test_json_formatter_includes_fields_and_request_id():
    record = logging.LogRecord("x", logging.INFO, "", 0, "hello", None, None)
    record.fields = {"order_id": "abc"}
    token = request_id.set("req-1")
    try:
        entry = json.loads(JsonFormatter("shop").format(record))
    finally:
        request_id.reset(token)
    assert entry["service"] == "shop"
    assert entry["level"] == "info"
    assert entry["msg"] == "hello"
    assert entry["request_id"] == "req-1"
    assert entry["order_id"] == "abc"


def test_request_id_is_propagated_to_response(client):
    response = client.get("/items/1", headers={"x-request-id": "req-42"})
    assert response.status_code == 200
    assert response.headers["x-request-id"] == "req-42"


def test_request_id_is_generated_when_missing(client):
    assert client.get("/items/1").headers["x-request-id"]


def test_metrics_use_route_template(client):
    client.get("/items/7")
    metrics = client.get("/metrics").text
    assert 'http_requests_total{method="GET",route="/items/{item_id}",status="200"}' in metrics


def test_unhandled_error_returns_500(client):
    response = client.get("/boom")
    assert response.status_code == 500
    assert response.json() == {"detail": "internal_error"}
