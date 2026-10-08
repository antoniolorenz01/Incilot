import pytest

from incilot_sim.injector.core import resolves

DEPLOY = {
    "action": "rollback",
    "culprit_sha": "1049b486889d6d674d31f4bb5e617aef8956bf38",
    "service": "inventory",
}
INFRA = {"action": "restart", "culprit_sha": None, "service": "redis"}


@pytest.mark.parametrize(
    ("injection", "kind", "target", "expected"),
    [
        (DEPLOY, "rollback", "1049b48", True),
        (DEPLOY, "revert_config", "1049b486889d", True),  # equivalent: both revert a commit
        (DEPLOY, "rollback", "9441aff", False),  # a decoy
        (DEPLOY, "rollback", "1049", False),  # SHA too short
        (DEPLOY, "revert_config", "config/inventory.env (commit 1049b48)", True),  # SHA in text
        (DEPLOY, "rollback", "1049b48 or 9441aff", True),
        (DEPLOY, "restart", "inventory", False),  # relieves it, but does not fix the bug
        (INFRA, "restart", "redis", True),
        (INFRA, "restart", "users", False),
        (INFRA, "escalate", "provider", False),
    ],
)
def test_resolves(injection, kind, target, expected):
    assert resolves(injection, kind, target) is expected
