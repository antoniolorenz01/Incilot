import asyncio
import json
import random
from datetime import UTC, datetime, timedelta

import pytest

from incilot_sim.company_repo import commit, git, revert
from incilot_sim.injector import timeline
from incilot_sim.injector.core import activate_faults, clear_faults
from incilot_sim.injector.scenarios import load, pick

SCENARIO = """
id = "deploy-latency-regression"
title = "Deploy con regresión de latencia"
category = "deploy"

[[variants]]
id = "slow-query"
service = "inventory"

[variants.culprit]
author = "diego"
message = "inventory: consulta nueva"

[[variants.culprit.edits]]
file = "app.env"
old = "TIMEOUT=1"
new = "TIMEOUT=9"

[variants.faults.inventory]
latency = { ms = 800 }

[variants.ground_truth]
root_cause = "consulta lenta"
action = "rollback"
"""

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)


class FakeRedis:
    def __init__(self):
        self.data = {}

    async def delete(self, *keys):
        for key in keys:
            self.data.pop(key, None)

    async def hset(self, key, mapping):
        self.data.setdefault(key, {}).update(mapping)


@pytest.fixture
def data(tmp_path):
    (tmp_path / "data/scenarios").mkdir(parents=True)
    (tmp_path / "data/history.toml").write_text('[authors]\ndiego = "Diego M <diego@t.example>"\n')
    (tmp_path / "data/scenarios/latency.toml").write_text(SCENARIO)
    return tmp_path / "data"


@pytest.fixture
def repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    (repo / "app.env").write_text("TIMEOUT=1\n")
    commit(repo, "Ana R <ana@t.example>", "inicial", datetime(2026, 10, 1, tzinfo=UTC))
    return repo


def test_load_resolves_culprit_author(data):
    variant = pick(load(data), "deploy-latency-regression", "slow-query")
    assert variant.service == "inventory"
    assert variant.culprit["author"] == "Diego M <diego@t.example>"
    assert variant.faults == {"inventory": {"latency": {"ms": 800}}}


def test_pick_rejects_unknown_scenario(data):
    with pytest.raises(KeyError):
        pick(load(data), "nope")


def decoy(message, file, old=None, new=None, content=None):
    edit = {"file": file, "content": content} if content else {"file": file, "old": old, "new": new}
    return {"author": "Ana R <ana@t.example>", "message": message, "edits": [edit]}


def test_culprit_is_never_the_last_commit_and_reverts_cleanly(data, repo):
    variant = pick(load(data), "deploy-latency-regression")
    decoys = [decoy(f"docs {i}", f"docs/{i}.md", content="x\n") for i in range(3)]
    steps = timeline.plan(repo, variant.culprit, decoys, NOW, random.Random(1))

    culprit = next(s for s in steps if s.culprit)
    assert not steps[-1].culprit
    assert NOW - timedelta(minutes=4) <= culprit.when <= NOW - timedelta(seconds=90)
    assert [s.when for s in steps] == sorted(s.when for s in steps)

    shas = {s.change["message"]: timeline.apply(repo, s) for s in steps}
    assert (repo / "app.env").read_text() == "TIMEOUT=9\n"
    revert(repo, shas["inventory: consulta nueva"], "Guardia SRE <sre@t.example>", NOW)
    assert (repo / "app.env").read_text() == "TIMEOUT=1\n"


def test_decoys_never_break_or_touch_the_culprit(data, repo):
    variant = pick(load(data), "deploy-latency-regression")
    breaks_culprit = decoy("rompe", "app.env", "TIMEOUT=1", "TIMEOUT=5")
    for seed in range(20):
        steps = timeline.plan(repo, variant.culprit, [breaks_culprit], NOW, random.Random(seed))
        assert [s.culprit for s in steps] == [True]


def test_already_applied_decoys_are_skipped(repo):
    applied = decoy("ya está", "app.env", "TIMEOUT=1\n", "TIMEOUT=1\nDEBUG=0\n")
    (repo / "app.env").write_text("TIMEOUT=1\nDEBUG=0\n")
    assert timeline.plan(repo, None, [applied], NOW, random.Random(0)) == []


def test_activate_and_clear_faults():
    redis = FakeRedis()
    redis.data["faults:inventory"] = {"errors": "{}"}  # restos de antes: se reemplazan
    asyncio.run(activate_faults(redis, {"inventory": {"latency": {"ms": 800}}}))
    assert redis.data == {"faults:inventory": {"latency": json.dumps({"ms": 800})}}
    asyncio.run(clear_faults(redis, ["inventory"]))
    assert redis.data == {}
