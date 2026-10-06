"""Runbooks de incidentes. Búsqueda simple por palabras clave (el RAG es TONI-78)."""

import re

from incilot_agent import config
from incilot_agent.tools._guard import ToolError, guarded

WORD = re.compile(r"\w{3,}")


@guarded(timeout=5)
async def search_runbooks(query: str, limit: int = 2) -> str:
    """Los runbooks más relevantes para `query` (p. ej. "latencia alta inventory"),
    con su contenido completo."""
    if not 1 <= limit <= 5:
        raise ToolError("limit tiene que estar entre 1 y 5")
    terms = set(WORD.findall(query.lower()))
    if not terms:
        raise ToolError("la búsqueda necesita al menos una palabra de 3 letras o más")
    scored = []
    for path in sorted(config.RUNBOOKS_DIR.glob("*.md")):
        text = path.read_text()
        words = WORD.findall(text.lower())
        score = sum(words.count(t) for t in terms) + 5 * sum(t in path.stem for t in terms)
        if score:
            scored.append((score, path.name, text))
    if not scored:
        names = ", ".join(p.stem for p in sorted(config.RUNBOOKS_DIR.glob("*.md")))
        return f"ningún runbook coincide con {query!r}. Disponibles: {names}"
    scored.sort(reverse=True)
    return "\n\n---\n\n".join(f"[{name}]\n{text}" for _, name, text in scored[:limit])
