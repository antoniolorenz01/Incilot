# Incilot

- Monorepo Python 3.12 con workspace de uv. Cada componente (`sim/`, y más adelante
  `agent/`, `evals/`) es un miembro del workspace con layout `src/`.
- Al agregar un miembro: sumarlo a `members`, a `dependencies` y a `[tool.uv.sources]`
  en el `pyproject.toml` raíz, y su carpeta de tests a `testpaths`.
- Antes de commitear: `make check` (ruff + pytest).
- Los datos sintéticos no van en este repo.
- Tareas en Linear, equipo TONI, proyecto IncidentPilot.
