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
        (DEPLOY, "revert_config", "1049b486889d", True),  # equivalentes: revierten un commit
        (DEPLOY, "rollback", "9441aff", False),  # un señuelo
        (DEPLOY, "rollback", "1049", False),  # SHA demasiado corto
        (DEPLOY, "restart", "inventory", False),  # alivia, pero no corrige el bug
        (INFRA, "restart", "redis", True),
        (INFRA, "restart", "users", False),
        (INFRA, "escalate", "proveedor", False),
    ],
)
def test_resolves(injection, kind, target, expected):
    assert resolves(injection, kind, target) is expected
