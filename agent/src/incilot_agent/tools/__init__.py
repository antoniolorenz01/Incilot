"""The agent's investigation tools. All of them are read-only.

Each one is an async function with typed arguments and a docstring, independent of the
framework: the agent's graph (TONI-77) wraps them. All have a timeout and a response size
limit, and return errors as text ("error: ...").
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
