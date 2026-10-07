import asyncio
import json
import subprocess

import httpx
import pytest
from pydantic import ValidationError

from incilot_agent import config
from incilot_agent.actions import ActionProposal
from incilot_agent.tools import (
    READ_ONLY_TOOLS,
    _http,
    list_commits,
    query_metrics,
    read_file,
    search_logs,
    show_commit,
)
from incilot_agent.tools._guard import MAX_CHARS, ToolError, fit_to_budget, guarded
from incilot_agent.tools.database import validate_sql


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def http(monkeypatch):
    """Reemplaza Prometheus/Loki por un handler; devuelve las requests recibidas."""
    seen = []

    def install(handler):
        def respond(request):
            seen.append(request)
            return handler(request)

        monkeypatch.setattr(
            _http,
            "client",
            lambda base_url: httpx.AsyncClient(
                base_url=base_url, transport=httpx.MockTransport(respond)
            ),
        )
        return seen

    return install


# --- guard ---------------------------------------------------------------------


def test_guard_turns_failures_into_text():
    @guarded(timeout=0.05)
    async def slow():
        await asyncio.sleep(1)

    @guarded(timeout=1)
    async def invalid():
        raise ToolError("argumento inválido")

    @guarded(timeout=1)
    async def huge():
        return "x" * (MAX_CHARS + 100)

    assert run(slow()).startswith("error: la herramienta tardó")
    assert run(invalid()) == "error: argumento inválido"
    assert "recortado: 100 caracteres" in run(huge())


# --- métricas ------------------------------------------------------------------


def test_query_metrics_summarizes_series(http):
    http(
        lambda r: httpx.Response(
            200,
            json={
                "status": "success",
                "data": {
                    "result": [
                        {"metric": {"service": "shop"}, "values": [[1, "1"], [2, "3"], [3, "2"]]}
                    ]
                },
            },
        )
    )
    out = run(query_metrics("rate(http_requests_total[1m])"))
    assert "service=shop: actual 2 | min 1 | max 3 | prom 2" in out


def test_query_metrics_reports_prometheus_errors(http):
    http(lambda r: httpx.Response(400, json={"status": "error", "error": "parse error"}))
    assert run(query_metrics("rate(")).startswith("error: Prometheus rechazó la consulta")


# --- logs ----------------------------------------------------------------------


def test_search_logs_builds_logql_from_filters(http):
    seen = http(
        lambda r: httpx.Response(
            200,
            json={
                "data": {
                    "result": [
                        {"stream": {"service": "shop"}, "values": [["1700000000000000000", "boom"]]}
                    ]
                }
            },
        )
    )
    out = run(search_logs(service="shop", level="error", contains='say "hi"'))
    assert seen[0].url.params["query"] == '{service="shop", level="error"} |= "say \\"hi\\""'
    assert "1× [shop]" in out
    assert "ej: boom" in out


def test_search_logs_rejects_unknown_service(http):
    http(lambda r: httpx.Response(500))
    assert run(search_logs(service="injector")).startswith("error: servicio desconocido")


# --- git -----------------------------------------------------------------------


@pytest.fixture
def repo(tmp_path, monkeypatch):
    def git(*args):
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True)

    git("init", "-q", "-b", "main")
    (tmp_path / "config").mkdir()
    (tmp_path / "config/shop.env").write_text("TIMEOUT=2\n")
    git("add", "-A")
    git("-c", "user.name=Ana", "-c", "user.email=a@t.example", "commit", "-qm", "config inicial")
    monkeypatch.setattr(config, "COMPANY_REPO", tmp_path)
    return tmp_path


def test_git_tools(repo):
    assert "Ana: config inicial" in run(list_commits())
    assert "config/shop.env" in run(list_commits(path="config"))
    assert "+TIMEOUT=2" in run(show_commit("HEAD"))
    assert run(read_file("config/shop.env")) == "TIMEOUT=2\n"


@pytest.mark.parametrize(
    "call",
    [
        lambda: read_file("../etc/passwd"),
        lambda: read_file("/etc/passwd"),
        lambda: read_file("config/shop.env", ref="--output=/tmp/x"),
        lambda: show_commit("HEAD; rm -rf /"),
        lambda: list_commits(path="--all"),
    ],
)
def test_git_tools_reject_unsafe_arguments(repo, call):
    assert run(call()).startswith(("error: ruta inválida", "error: referencia inválida"))


# --- runbooks ------------------------------------------------------------------


# --- base de datos -------------------------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM products",
        "select pid, query from pg_stat_activity where wait_event_type = 'Lock';",
        "WITH x AS (SELECT 1) SELECT * FROM x",
        "EXPLAIN SELECT * FROM reservations",
        "SELECT created_at, updated_at FROM orders -- update comentado",
    ],
)
def test_validate_sql_accepts_reads(sql):
    validate_sql(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE users SET name = 'x'",
        "SELECT 1; DROP TABLE users",
        "WITH d AS (DELETE FROM orders RETURNING *) SELECT * FROM d",
        "SELECT pg_terminate_backend(123)",
        "SELECT pg_sleep(10)",
        "EXPLAIN ANALYZE DELETE FROM orders",
        "LOCK TABLE products",
        "SELECT set_config('statement_timeout', '0', false)",
    ],
)
def test_validate_sql_rejects_writes_and_side_effects(sql):
    with pytest.raises(ToolError):
        validate_sql(sql)


# --- acciones ------------------------------------------------------------------


def test_actions_always_require_approval():
    action = ActionProposal(kind="rollback", target="abc1234", reason="r", evidence=["e"])
    assert action.requires_approval is True
    with pytest.raises(ValidationError):
        ActionProposal(
            kind="rollback", target="x", reason="r", evidence=[], requires_approval=False
        )


def test_tools_are_read_only():
    names = {t.__name__ for t in READ_ONLY_TOOLS}
    assert names == {
        "query_metrics",
        "search_logs",
        "list_commits",
        "show_commit",
        "read_file",
        "search_knowledge",
        "query_database",
    }


# --- gestión de contexto -------------------------------------------------------


def test_search_logs_groups_repeated_lines_by_pattern(http):
    def line(rid, user, exc):
        return json.dumps(
            {
                "level": "error",
                "service": "users",
                "msg": "unhandled error",
                "request_id": rid,
                "path": f"/users/{user}",
                "exc": f"Traceback...\n{exc}",
            }  # fmt: skip
        )

    values = [
        [str(1700000000 + i) + "000000000", line(f"r{i}", i, "KeyError: 'trial'")]
        for i in range(40)
    ]
    values += [["1700000100000000000", line("x", 7, "ConnectionResetError: [Errno 104] reset")]]
    http(
        lambda r: httpx.Response(
            200, json={"data": {"result": [{"stream": {"service": "users"}, "values": values}]}}
        )
    )

    out = run(search_logs(service="users"))
    assert out.startswith("41 líneas en 2 patrones")
    assert "\n40× [users]" in out
    assert "\n1× [users]" in out
    assert out.count("ej: ") == 2


def test_fit_to_budget_keeps_short_outputs_and_trims_long_ones():
    short, long_a, long_b = "a" * 100, "b" * 5000, "c" * 5000
    fitted = fit_to_budget([short, long_a, long_b], 3000)
    assert fitted[0] == short
    assert sum(map(len, fitted)) <= 3000
    assert all("recortado por el presupuesto" in f for f in fitted[1:])
    assert fit_to_budget([short], 3000) == [short]
