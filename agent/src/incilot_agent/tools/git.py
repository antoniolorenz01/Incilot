"""Historial y archivos del repo Git de la empresa (montado en solo lectura).

Solo `git log` y `git show`, sin shell, con argumentos validados: un SHA o un
`HEAD~n` como referencia, y rutas relativas dentro del repo.
"""

import asyncio
import os
import re

from incilot_agent import config
from incilot_agent.tools._guard import ToolError, guarded

REF = re.compile(r"^([0-9a-f]{4,40}|HEAD(~\d{1,3})?)$")


def _check_ref(ref: str) -> str:
    if not REF.match(ref):
        raise ToolError(f"referencia inválida: {ref!r}. Usá un SHA o HEAD~n")
    return ref


def _check_path(path: str) -> str:
    if path.startswith(("/", "-")) or ".." in path.split("/") or "\\" in path:
        raise ToolError(f"ruta inválida: {path!r}. Tiene que ser relativa al repo")
    return path


async def _git(*args: str) -> str:
    process = await asyncio.create_subprocess_exec(
        "git",
        "-C",
        str(config.COMPANY_REPO),
        "--no-pager",
        # El repo es de otro usuario (montado en solo lectura): confiar en él.
        "-c",
        "safe.directory=*",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        # Aislado de la config del sistema: nada de hooks, alias ni pagers.
        env={
            "PATH": os.environ["PATH"],
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
        },
    )
    try:
        out, err = await process.communicate()
    finally:
        if process.returncode is None:
            process.kill()
    if process.returncode != 0:
        raise ToolError(err.decode().strip() or f"git terminó con código {process.returncode}")
    return out.decode()


@guarded(timeout=10)
async def list_commits(since_minutes: int = 1440, path: str | None = None, limit: int = 20) -> str:
    """Commits de los últimos `since_minutes` minutos (más nuevos primero), con autor,
    fecha y archivos tocados. `path` limita a un archivo o carpeta (p. ej. config/shop.env)."""
    if not 1 <= limit <= 100:
        raise ToolError("limit tiene que estar entre 1 y 100")
    args = [
        "log",
        f"--since={since_minutes} minutes ago",
        f"--max-count={limit}",
        "--date=iso",
        "--format=%h %ad %an: %s",
        "--name-only",
    ]
    if path:
        args += ["--", _check_path(path)]
    out = await _git(*args)
    return out.strip() or f"sin commits en los últimos {since_minutes} minutos"


@guarded(timeout=10)
async def show_commit(sha: str) -> str:
    """Un commit completo: autor, fecha, mensaje y diff."""
    return await _git("show", "--date=iso", "--stat", "--patch", _check_ref(sha))


@guarded(timeout=10)
async def read_file(path: str, ref: str = "HEAD") -> str:
    """Contenido de un archivo del repo en una versión (por defecto la actual).
    Útil para la config de cada servicio: config/<servicio>.env."""
    return await _git("show", f"{_check_ref(ref)}:{_check_path(path)}")
