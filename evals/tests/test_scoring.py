import pytest

from incilot_evals.scoring import commit_verdict, score

DEPLOY = {
    "service": "inventory",
    "action": "rollback",
    "culprit_sha": "82582b15bdeae4dde6e06640b5ba063b92d49880",
    "decoy_shas": ["e8c29c6aaaa", "f02a404bbbb"],
}
INFRA = {"service": "redis", "action": "restart", "culprit_sha": None, "decoy_shas": ["9441aff"]}


def diagnosis(service, commit, kind, target):
    return {
        "service": service,
        "culprit_commit": commit,
        "action": {"kind": kind, "target": target},
    }


def test_correct_diagnosis():
    result = score(DEPLOY, diagnosis("inventory", "82582b1", "rollback", "82582b1"))
    assert result == {"action_ok": True, "service_ok": True, "commit": "correct", "commit_ok": True}


def test_todays_run_found_the_commit_but_proposed_the_wrong_action():
    """La corrida de TONI-79: encontró el commit pero escaló a infraestructura."""
    result = score(
        DEPLOY,
        diagnosis("infraestructura compartida (Redis y Postgres)", None, "escalate", "plataforma"),
    )
    assert result["action_ok"] is False
    assert result["service_ok"] is False


@pytest.mark.parametrize(
    ("truth", "given", "verdict"),
    [
        (DEPLOY, "82582b1", "correct"),
        (DEPLOY, "f02a404", "decoy"),
        (DEPLOY, "1234567", "wrong"),
        (DEPLOY, None, "missing"),
        (DEPLOY, "8258", "wrong"),  # SHA demasiado corto
        (INFRA, None, "correct_none"),
        (INFRA, "9441aff", "blamed_innocent"),
    ],
)
def test_commit_verdict(truth, given, verdict):
    assert commit_verdict(truth, given) == verdict


def test_service_must_be_named_as_a_word():
    def named(text):
        return score(DEPLOY, diagnosis(text, None, "x", "y"))["service_ok"]

    assert named("inventory")
    assert named("Inventory (catálogo)")
    assert named("inventory-api")
    assert not named("inventoryservice")
    assert not named("shop")
