import asyncio
import json
from datetime import UTC, datetime

import pytest

from incilot_sim.company_repo import commit, git, revert
from incilot_sim.injector.core import activate_faults, clear_faults, commit_culprit
from incilot_sim.injector.scenarios import load, pick

SCENARIO = """
id = "deploy-latency-regression"
title = "Deploy con regresión de latencia"
category = "deploy"

[[variants]]
id = "slow-query"
service = "inventory"

[variants.culprit]
minutes_ago = 10
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


def test_culprit_commit_and_rollback(data, repo):
    variant = pick(load(data), "deploy-latency-regression")
    sha = commit_culprit(repo, variant.culprit, NOW)
    assert (repo / "app.env").read_text() == "TIMEOUT=9\n"
    log = git(repo, "log", "-1", "--format=%an|%ad|%s", "--date=format:%H:%M")
    assert log.strip() == "Diego M|11:50|inventory: consulta nueva"

    revert(repo, sha, "Guardia SRE <sre@t.example>", NOW)
    assert (repo / "app.env").read_text() == "TIMEOUT=1\n"


def test_activate_and_clear_faults():
    redis = FakeRedis()
    redis.data["faults:inventory"] = {"errors": "{}"}  # restos de antes: se reemplazan
    asyncio.run(activate_faults(redis, {"inventory": {"latency": {"ms": 800}}}))
    assert redis.data == {"faults:inventory": {"latency": json.dumps({"ms": 800})}}
    asyncio.run(clear_faults(redis, ["inventory"]))
    assert redis.data == {}
