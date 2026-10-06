"""Línea de tiempo de una inyección en el repo de la empresa: culpable y señuelos.

El commit culpable es "el deploy" que dispara el fallo: se fecha unos minutos antes
del inicio de los síntomas. Alrededor van commits señuelo (incilot-data/decoys.toml),
inocentes pero creíbles, para que el último commit no sea la respuesta:

    señuelos "antes"  →  culpable (hace 1,5–4 min)  →  señuelos "después"  →  ahora

En fallos sin culpable (infraestructura, externos) solo hay señuelos recientes.
"""

import random
import tomllib
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from incilot_sim.company_repo import apply_edit, commit


@dataclass(frozen=True)
class Step:
    change: dict  # author, message, edits
    when: datetime
    culprit: bool


def load_decoys(data: Path, authors: dict[str, str]) -> list[dict]:
    path = data / "decoys.toml"
    if not path.exists():
        return []
    decoys = tomllib.loads(path.read_text())["decoys"]
    return [d | {"author": authors[d["author"]]} for d in decoys]


def plan(
    repo: Path, culprit: dict | None, decoys: list[dict], now: datetime, rng: random.Random
) -> list[Step]:
    candidates = decoys[:]
    rng.shuffle(candidates)
    files: dict[str, str | None] = {}  # estado simulado del repo tras los commits elegidos
    culprit_edits = culprit["edits"] if culprit else []
    culprit_files = {e["file"] for e in culprit_edits}
    n_before, n_after = (
        (rng.randint(0, 1), rng.randint(1, 2)) if culprit else (0, rng.randint(1, 3))
    )
    before, after = [], []

    for decoy in candidates:
        decoy_files = {e["file"] for e in decoy["edits"]}
        trial = dict(files)
        if not _simulate(repo, decoy["edits"], trial):
            continue
        # Antes del culpable: vale si el culpable se sigue pudiendo aplicar encima.
        if len(before) < n_before and _simulate(repo, culprit_edits, dict(trial)):
            before.append(decoy)
            files = trial
        # Después: no puede tocar los archivos del culpable (el rollback tiene que
        # revertir limpio).
        elif len(after) < n_after and not decoy_files & culprit_files:
            after.append(decoy)
            files = trial

    if culprit is None:
        times = sorted(now - timedelta(minutes=rng.uniform(1, 30)) for _ in after)
        return [Step(d, t, False) for d, t in zip(after, times, strict=True)]

    deployed = now - timedelta(seconds=rng.uniform(90, 240))
    before_times = sorted(deployed - timedelta(minutes=rng.uniform(5, 60)) for _ in before)
    after_times = sorted(deployed + (now - deployed) * rng.uniform(0.15, 0.85) for _ in after)
    return (
        [Step(d, t, False) for d, t in zip(before, before_times, strict=True)]
        + [Step(culprit, deployed, True)]
        + [Step(d, t, False) for d, t in zip(after, after_times, strict=True)]
    )


def apply(repo: Path, step: Step) -> str:
    """Aplica el cambio en el repo y lo commitea con su autor y fecha. Devuelve el sha."""
    for edit in step.change["edits"]:
        path = repo / edit["file"]
        if "content" in edit:  # archivo nuevo
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(edit["content"])
        else:
            apply_edit(path, edit["old"], edit["new"])
    return commit(repo, step.change["author"], step.change["message"], step.when)


def _simulate(repo: Path, edits: list[dict], files: dict[str, str | None]) -> bool:
    """Aplica los cambios sobre `files` (en memoria). False si alguno no se puede aplicar
    o ya está aplicado."""
    for edit in edits:
        name = edit["file"]
        if name not in files:
            path = repo / name
            files[name] = path.read_text() if path.exists() else None
        text = files[name]
        if "content" in edit:
            if text is not None:
                return False
            files[name] = edit["content"]
        else:
            if text is None or text.count(edit["old"]) != 1:
                return False
            # Un cambio que agrega texto deja el original: está aplicado si ya está lo nuevo.
            if edit["old"] in edit["new"] and edit["new"] in text:
                return False
            files[name] = text.replace(edit["old"], edit["new"])
    return True
