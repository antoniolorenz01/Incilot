"""The agent's language models: retries, timeouts and fallback.

- Retries with exponential backoff and a per-call timeout: handled by the OpenAI SDK
  (rate limits, 5xx, dropped connections). Configured with LLM_MAX_RETRIES and
  LLM_TIMEOUT_SECONDS.
- Fallback: if a model keeps failing after its retries, the next one in the list is
  used (OPENAI_MODEL, then OPENAI_FALLBACK_MODEL). Every fallback is recorded.
  If all of them fail, the call fails: the investigation can be resumed with --resume.
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


def agent_models() -> list[BaseChatModel]:
    """The configured provider: OpenAI (default) or, locally, Claude Code."""
    if os.getenv("LLM_PROVIDER", "openai") == "claude-code":
        from incilot_agent.claude_code import claude_code_models

        return claude_code_models()
    return openai_models()


def dry_run_models() -> list[BaseChatModel]:
    """Fake LLM for `dry_run`: uses one real tool and submits a test diagnosis.
    Zero tokens: for testing the API and the dashboard."""
    from incilot_agent.testing import DIAGNOSIS, FakeLLM, call

    diagnosis = DIAGNOSIS | {"service": "dry-run", "root_cause": "simulated investigation"}
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
    """Tries each model in order. Returns (result, recorded failure events)."""
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
    raise RuntimeError("no models configured")
