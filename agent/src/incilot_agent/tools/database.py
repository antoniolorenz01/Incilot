"""Consultas SQL de solo lectura a las bases de los servicios.

Tres capas de defensa: esta deny-list, una transacción de solo lectura con timeout,
y el usuario `agent` de Postgres, que de por sí solo puede leer.
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
# Lo que podría colarse dentro de un SELECT/WITH: CTEs que modifican datos, EXPLAIN
# ANALYZE (ejecuta la consulta) y funciones con efectos.
FORBIDDEN = re.compile(
    r"\b(insert|update|delete|merge|drop|alter|create|truncate|grant|revoke|copy|analyze|"
    r"pg_terminate_backend|pg_cancel_backend|pg_sleep\w*|pg_read_file|pg_read_binary_file|"
    r"pg_ls_dir|lo_import|lo_export|dblink\w*|set_config|pg_reload_conf)\b",
    re.IGNORECASE,
)


def validate_sql(sql: str) -> str:
    """Devuelve la consulta limpia, o lanza ToolError si no es una lectura simple."""
    cleaned = re.sub(r"--[^\n]*|/\*.*?\*/", " ", sql, flags=re.DOTALL).strip().rstrip(";")
    if ";" in cleaned:
        raise ToolError("una sola sentencia por consulta")
    if not ALLOWED_START.match(cleaned):
        raise ToolError("solo se permiten consultas SELECT, WITH o EXPLAIN")
    if match := FORBIDDEN.search(cleaned):
        raise ToolError(f"operación no permitida: {match.group(0)}")
    return cleaned


@guarded(timeout=10)
async def query_database(database: Database, sql: str) -> str:
    """SQL de solo lectura sobre la base de un servicio (users, inventory, payments, shop).

    Además de las tablas del servicio se pueden consultar las vistas de diagnóstico de
    Postgres: pg_stat_activity (sesiones y qué esperan), pg_locks, pg_stat_user_tables.
    Devuelve como mucho 50 filas.
    """
    if database not in ("users", "inventory", "payments", "shop"):
        raise ToolError("database tiene que ser users, inventory, payments o shop")
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
        return "0 filas"
    columns = list(rows[0].keys())
    lines = [" | ".join(columns)]
    for row in rows[:MAX_ROWS]:
        lines.append(" | ".join(str(v)[:MAX_CELL] for v in row.values()))
    if len(rows) > MAX_ROWS:
        lines.append(f"… más de {MAX_ROWS} filas: agregá filtros o un LIMIT")
    return "\n".join(lines)
