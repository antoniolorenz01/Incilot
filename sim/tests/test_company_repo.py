import subprocess
from datetime import UTC, datetime

import pytest

from incilot_sim.company_repo import build

HISTORY = """
[authors]
ana = "Ana Ruiz <ana@shop.example>"

[[commits]]
days_ago = 2
time = "10:00"
author = "ana"
message = "initial config"
add = ["app.env"]

[[commits]]
days_ago = 1
time = "09:30"
author = "ana"
message = "raise timeout"

[[commits.edits]]
file = "app.env"
old = "TIMEOUT=1"
new = "TIMEOUT=2"
"""


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True).stdout


@pytest.fixture
def data(tmp_path):
    (tmp_path / "data/files").mkdir(parents=True)
    (tmp_path / "data/files/app.env").write_text("TIMEOUT=1\n")
    (tmp_path / "data/history.toml").write_text(HISTORY)
    return tmp_path / "data"


def test_build_replays_history_with_authors_and_dates(data, tmp_path):
    out = tmp_path / "repo"
    build(data, out, datetime(2026, 10, 2, tzinfo=UTC))
    log = git(out, "log", "--format=%an|%ad|%s", "--date=format:%Y-%m-%d %H:%M").splitlines()
    assert log == [
        "Ana Ruiz|2026-10-01 09:30|raise timeout",
        "Ana Ruiz|2026-09-30 10:00|initial config",
    ]
    assert (out / "app.env").read_text() == "TIMEOUT=2\n"


def test_build_fails_if_edit_does_not_match(data, tmp_path):
    (data / "history.toml").write_text(HISTORY.replace('old = "TIMEOUT=1"', 'old = "NOPE"'))
    with pytest.raises(ValueError, match="appears 0 times"):
        build(data, tmp_path / "repo", datetime(2026, 10, 2, tzinfo=UTC))
