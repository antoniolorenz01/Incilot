"""Timeline of an injection in the company repo: culprit and decoys.

The culprit commit is "the deploy" that triggers the fault: it is dated a few minutes
before the symptoms start. Around it go decoy commits (incilot-data/decoys.toml),
innocent but believable, so that the latest commit is not the answer:

    "before" decoys  →  culprit (1.5–4 min ago)  →  "after" decoys  →  now

For faults with no culprit (infrastructure, external) there are only recent decoys.
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
    files: dict[str, str | None] = {}  # simulated repo state after the chosen commits
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
        # Before the culprit: fine if the culprit can still be applied on top.
        if len(before) < n_before and _simulate(repo, culprit_edits, dict(trial)):
            before.append(decoy)
            files = trial
        # After: must not touch the culprit's files (the rollback has to
        # revert cleanly).
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
    """Applies the change to the repo and commits it with its author and date. Returns the sha."""
    for edit in step.change["edits"]:
        path = repo / edit["file"]
        if "content" in edit:  # new file
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(edit["content"])
        else:
            apply_edit(path, edit["old"], edit["new"])
    return commit(repo, step.change["author"], step.change["message"], step.when)


def _simulate(repo: Path, edits: list[dict], files: dict[str, str | None]) -> bool:
    """Applies the changes to `files` (in memory). False if any cannot be applied
    or is already applied."""
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
            # A change that adds text keeps the original: it is applied if the new text is there.
            if edit["old"] in edit["new"] and edit["new"] in text:
                return False
            files[name] = text.replace(edit["old"], edit["new"])
    return True
