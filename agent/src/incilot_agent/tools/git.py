"""History and files of the company's Git repo (mounted read-only).

Only `git log` and `git show`, without a shell, with validated arguments: a SHA or
`HEAD~n` as the reference, and relative paths inside the repo.
"""

import asyncio
import os
import re

from incilot_agent import config
from incilot_agent.tools._guard import ToolError, guarded

REF = re.compile(r"^([0-9a-f]{4,40}|HEAD(~\d{1,3})?)$")


def _check_ref(ref: str) -> str:
    if not REF.match(ref):
        raise ToolError(f"invalid reference: {ref!r}. Use a SHA or HEAD~n")
    return ref


def _check_path(path: str) -> str:
    if path.startswith(("/", "-")) or ".." in path.split("/") or "\\" in path:
        raise ToolError(f"invalid path: {path!r}. It must be relative to the repo")
    return path


async def _git(*args: str) -> str:
    process = await asyncio.create_subprocess_exec(
        "git",
        "-C",
        str(config.COMPANY_REPO),
        "--no-pager",
        # The repo belongs to another user (mounted read-only): trust it.
        "-c",
        "safe.directory=*",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        # Isolated from the system config: no hooks, aliases or pagers.
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
        raise ToolError(err.decode().strip() or f"git exited with code {process.returncode}")
    return out.decode()


@guarded(timeout=10)
async def list_commits(since_minutes: int = 1440, path: str | None = None, limit: int = 20) -> str:
    """Commits from the last `since_minutes` minutes (newest first), with author, date
    and files touched. `path` restricts to a file or directory (e.g. config/shop.env)."""
    if not 1 <= limit <= 100:
        raise ToolError("limit must be between 1 and 100")
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
    return out.strip() or f"no commits in the last {since_minutes} minutes"


@guarded(timeout=10)
async def show_commit(sha: str) -> str:
    """A full commit: author, date, message and diff."""
    return await _git("show", "--date=iso", "--stat", "--patch", _check_ref(sha))


@guarded(timeout=10)
async def read_file(path: str, ref: str = "HEAD") -> str:
    """Contents of a repo file at a given version (the current one by default).
    Useful for each service's config: config/<service>.env."""
    return await _git("show", f"{_check_ref(ref)}:{_check_path(path)}")
