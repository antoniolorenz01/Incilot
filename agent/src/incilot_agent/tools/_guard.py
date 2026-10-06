"""Lo que comparten todas las herramientas: timeout, límite de tamaño y errores legibles.

El agente nunca recibe una excepción: recibe un texto que puede leer y corregir
("error: ..."), y nunca una respuesta más larga que MAX_CHARS.
"""

import asyncio
import functools

MAX_CHARS = 8000


class ToolError(Exception):
    """Error que se le muestra al agente tal cual (p. ej. un argumento inválido)."""


def truncate(text: str, limit: int = MAX_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n… [recortado: {len(text) - limit} caracteres más]"


def fit_to_budget(outputs: list[str], budget: int) -> list[str]:
    """Reparte `budget` caracteres entre las salidas de una ronda, en partes justas: las
    cortas quedan completas y lo que les sobra se reparte entre las largas, que se recortan.
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
    note = (
        "\n… [recortado por el presupuesto de la ronda: "
        "pedí menos herramientas a la vez o filtrá más]"
    )
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
                return f"error: la herramienta tardó más de {timeout:g} s"
            except Exception as exc:  # noqa: BLE001 - el agente debe ver cualquier fallo
                return f"error: {type(exc).__name__}: {exc}"
            return truncate(result)

        return wrapper

    return decorate
