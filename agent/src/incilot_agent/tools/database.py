"""Read-only SQL queries against the services' databases.

Three layers of defence: this deny-list, a read-only transaction with a timeout, and
the Postgres user `agent`, which can only read in the first place.
"""

import re
from typing import Literal

import asyncpg

from incilot_agent import config
from incilot_agent.tools._guard import ToolError, guarded

Database = Literal["users", "inventory", "payments", "shop"]
MAX_ROWS = 50
MAX_CELL = 200
ALLOWED_START = re.compile(r"^\s*(select|with|explain)\b", re.IGNORECASE)
# What could sneak in inside a SELECT/WITH: data-modifying CTEs, EXPLAIN ANALYZE
# (which runs the query) and functions with side effects.
FORBIDDEN = re.compile(
    r"\b(insert|update|delete|merge|drop|alter|create|truncate|grant|revoke|copy|analyze|"
    r"pg_terminate_backend|pg_cancel_backend|pg_sleep\w*|pg_read_file|pg_read_binary_file|"
    r"pg_ls_dir|lo_import|lo_export|dblink\w*|set_config|pg_reload_conf)\b",
    re.IGNORECASE,
)


def validate_sql(sql: str) -> str:
    """Returns the cleaned query, or raises ToolError if it is not a plain read."""
    cleaned = re.sub(r"--[^\n]*|/\*.*?\*/", " ", sql, flags=re.DOTALL).strip().rstrip(";")
    if ";" in cleaned:
        raise ToolError("only one statement per query")
    if not ALLOWED_START.match(cleaned):
        raise ToolError("only SELECT, WITH or EXPLAIN queries are allowed")
    if match := FORBIDDEN.search(cleaned):
        raise ToolError(f"operation not allowed: {match.group(0)}")
    return cleaned


@guarded(timeout=10)
async def query_database(database: Database, sql: str) -> str:
    """Read-only SQL against a service's database (users, inventory, payments, shop).

    Besides the service's tables you can query Postgres's diagnostic views:
    pg_stat_activity (sessions and what they are waiting on), pg_locks,
    pg_stat_user_tables. Returns at most 50 rows.
    """
    if database not in ("users", "inventory", "payments", "shop"):
        raise ToolError("database must be users, inventory, payments or shop")
    sql = validate_sql(sql)
    conn = await asyncpg.connect(
        host=config.POSTGRES_HOST,
        port=config.POSTGRES_PORT,
        user=config.AGENT_DB_USER,
        password=config.AGENT_DB_PASSWORD,
        database=database,
        timeout=5,
        server_settings={"statement_timeout": "5000", "application_name": "incidentpilot"},
    )
    try:
        if sql.lower().startswith("explain"):
            query = sql
        else:
            query = f"SELECT * FROM ({sql}) AS q LIMIT {MAX_ROWS + 1}"
        async with conn.transaction(readonly=True):
            rows = await conn.fetch(query)
    except asyncpg.PostgresError as exc:
        raise ToolError(f"Postgres: {exc}") from None
    finally:
        await conn.close()

    if not rows:
        return "0 rows"
    columns = list(rows[0].keys())
    lines = [" | ".join(columns)]
    for row in rows[:MAX_ROWS]:
        lines.append(" | ".join(str(v)[:MAX_CELL] for v in row.values()))
    if len(rows) > MAX_ROWS:
        lines.append(f"… more than {MAX_ROWS} rows: add filters or a LIMIT")
    return "\n".join(lines)
