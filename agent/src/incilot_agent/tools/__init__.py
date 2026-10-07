"""Herramientas de investigación del agente. Todas son de solo lectura.

Cada una es una función async con argumentos tipados y docstring, independiente del
framework: el grafo del agente (TONI-77) las envuelve. Todas tienen timeout, límite de
tamaño de respuesta y devuelven los errores como texto ("error: ...").
"""

from incilot_agent.tools.database import query_database
from incilot_agent.tools.git import list_commits, read_file, show_commit
from incilot_agent.tools.knowledge import search_knowledge
from incilot_agent.tools.logs import search_logs
from incilot_agent.tools.metrics import query_metrics

READ_ONLY_TOOLS = [
    query_metrics,
    search_logs,
    list_commits,
    show_commit,
    read_file,
    search_knowledge,
    query_database,
]

__all__ = [t.__name__ for t in READ_ONLY_TOOLS] + ["READ_ONLY_TOOLS"]
