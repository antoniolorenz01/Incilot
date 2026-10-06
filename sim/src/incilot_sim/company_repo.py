"""Genera el repo Git de la mini-empresa a partir de incilot-data.

    python -m incilot_sim.company_repo --data ../incilot-data --out build/company-repo

El repo se regenera desde cero en cada ejecución. Las fechas de los commits son
relativas a `now`, así el historial siempre termina "hace unos días".
"""

import argparse
import os
import shutil
import subprocess
import tomllib
from datetime import UTC, datetime, time, timedelta
from pathlib import Path


def build(data: Path, out: Path, now: datetime) -> None:
    history = tomllib.loads((data / "history.toml").read_text())
    files = data / "files"
    unused = {p.relative_to(files) for p in files.rglob("*") if p.is_file()}

    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    git(out, "init", "-q", "-b", "main")

    for entry in history["commits"]:
        for path in entry.get("add", []):
            (out / path).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(files / path, out / path)
            unused.discard(Path(path))
        for edit in entry.get("edits", []):
            apply_edit(out / edit["file"], edit["old"], edit["new"])
        day = (now - timedelta(days=entry["days_ago"])).date()
        when = datetime.combine(day, time.fromisoformat(entry["time"]), tzinfo=UTC)
        commit(out, history["authors"][entry["author"]], entry["message"], when)

    if unused:
        raise ValueError(f"archivos de files/ que ningún commit agrega: {sorted(map(str, unused))}")


def apply_edit(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    if text.count(old) != 1:
        raise ValueError(f"{path}: el texto a reemplazar aparece {text.count(old)} veces:\n{old}")
    path.write_text(text.replace(old, new))


def commit(repo: Path, author: str, message: str, when: datetime) -> str:
    """Commitea todo lo pendiente con el autor y la fecha dados. Devuelve el sha."""
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message, env=_identity(author, when))
    return git(repo, "rev-parse", "HEAD").strip()


def revert(repo: Path, sha: str, author: str, when: datetime) -> str:
    """Revierte un commit (el rollback de un deploy). Devuelve el sha del revert."""
    git(repo, "revert", "--no-edit", sha, env=_identity(author, when))
    return git(repo, "rev-parse", "HEAD").strip()


def _identity(author: str, when: datetime) -> dict:
    name, email = author.removesuffix(">").split(" <")
    return {
        "GIT_AUTHOR_NAME": name,
        "GIT_AUTHOR_EMAIL": email,
        "GIT_AUTHOR_DATE": when.isoformat(),
        "GIT_COMMITTER_NAME": name,
        "GIT_COMMITTER_EMAIL": email,
        "GIT_COMMITTER_DATE": when.isoformat(),
    }


def git(repo: Path, *args: str, env: dict | None = None) -> str:
    # Aislado de la config global del usuario (firmas, hooks, plantillas).
    base_env = {
        "PATH": os.environ["PATH"],
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
    }
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        env=base_env | (env or {}),
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", type=Path, default=Path("../incilot-data"))
    parser.add_argument("--out", type=Path, default=Path("build/company-repo"))
    args = parser.parse_args()
    build(args.data, args.out, datetime.now(UTC))
    print(f"repo de la empresa generado en {args.out}")


if __name__ == "__main__":
    main()
