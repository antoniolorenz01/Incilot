"""Modelos de lenguaje del agente: retries, timeouts y fallback.

- Retries con backoff exponencial y timeout por llamada: los hace el SDK de OpenAI
  (rate limit, 5xx, cortes de conexión). Se configuran con LLM_MAX_RETRIES y
  LLM_TIMEOUT_SECONDS.
- Fallback: si un modelo sigue fallando tras sus retries, se usa el siguiente de la
  lista (OPENAI_MODEL y después OPENAI_FALLBACK_MODEL). Cada caída queda registrada.
  Si fallan todos, la llamada falla: la investigación se puede retomar con --resume.
"""

import os
from datetime import UTC, datetime

from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import Runnable

LLM_TIMEOUT_SECONDS = float(os.getenv("LLM_TIMEOUT_SECONDS", "60"))
LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "3"))


def openai_models() -> list[BaseChatModel]:
    from langchain_openai import ChatOpenAI

    names = [os.environ["OPENAI_MODEL"]]
    if fallback := os.getenv("OPENAI_FALLBACK_MODEL"):
        names.append(fallback)
    return [
        ChatOpenAI(model=name, timeout=LLM_TIMEOUT_SECONDS, max_retries=LLM_MAX_RETRIES)
        for name in names
    ]


def dry_run_models() -> list[BaseChatModel]:
    """LLM simulado para `dry_run`: usa una herramienta real y entrega un diagnóstico de
    prueba. Cero tokens: para probar la API y el dashboard."""
    from incilot_agent.testing import DIAGNOSIS, FakeLLM, call

    diagnosis = DIAGNOSIS | {"service": "dry-run", "root_cause": "investigación simulada"}
    query = "sum by (service) (rate(http_requests_total[1m]))"
    return [
        FakeLLM(
            replies=[
                call("query_metrics", {"promql": query, "minutes": 5}, "dry-1"),
                call("submit_diagnosis", diagnosis, "dry-2"),
            ]
        )
    ]


def model_name(llm: BaseChatModel) -> str:
    return getattr(llm, "model_name", None) or type(llm).__name__


async def invoke_with_fallback(candidates: list[tuple[str, Runnable]], messages: list):
    """Prueba cada modelo en orden. Devuelve (resultado, eventos de fallos registrados)."""
    events = []
    for index, (name, runnable) in enumerate(candidates):
        try:
            return await runnable.ainvoke(messages), events
        except Exception as exc:
            events.append(
                {
                    "at": datetime.now(UTC).isoformat(timespec="seconds"),
                    "model": name,
                    "error": f"{type(exc).__name__}: {exc}"[:300],
                    "fallback_to": candidates[index + 1][0]
                    if index + 1 < len(candidates)
                    else None,
                }
            )
            if index + 1 == len(candidates):
                raise
    raise RuntimeError("no hay modelos configurados")
