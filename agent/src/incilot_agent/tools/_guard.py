"""What all the tools share: timeout, size limit and readable errors.

The agent never receives an exception: it receives text it can read and act on
("error: ..."), and never a response longer than MAX_CHARS.
"""

import asyncio
import functools

MAX_CHARS = 8000


class ToolError(Exception):
    """An error shown to the agent as is (e.g. an invalid argument)."""


def truncate(text: str, limit: int = MAX_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n… [truncated: {len(text) - limit} more characters]"


def fit_to_budget(outputs: list[str], budget: int) -> list[str]:
    """Share `budget` characters fairly among a round's outputs: short ones stay whole
    and what they leave over is shared among the long ones, which get truncated.
    """
    if sum(map(len, outputs)) <= budget:
        return outputs
    limits = {}
    remaining, pending = budget, sorted(range(len(outputs)), key=lambda i: len(outputs[i]))
    while pending:
        share = remaining // len(pending)
        index = pending.pop(0)
        limits[index] = min(len(outputs[index]), share)
        remaining -= limits[index]
    note = "\n… [truncated by the round's budget: request fewer tools at once or filter more]"
    return [
        text if len(text) <= limits[i] else text[: max(limits[i] - len(note), 0)] + note
        for i, text in enumerate(outputs)
    ]


def guarded(timeout: float):
    def decorate(fn):
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs) -> str:
            try:
                result = await asyncio.wait_for(fn(*args, **kwargs), timeout)
            except ToolError as exc:
                return f"error: {exc}"
            except TimeoutError:
                return f"error: the tool took longer than {timeout:g} s"
            except Exception as exc:  # noqa: BLE001 - the agent must see any failure
                return f"error: {type(exc).__name__}: {exc}"
            return truncate(result)

        return wrapper

    return decorate
