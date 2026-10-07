"""Corrección de un diagnóstico contra el ground truth.

Nota principal (`action_ok`): ¿la acción propuesta resolvería el incidente? Es la misma
regla que usa el ejecutor de acciones (incilot_sim.injector.core.resolves).

Notas secundarias, para entender en qué falló:
    service_ok   ¿nombró el servicio donde está la causa?
    commit       correct · decoy (culpó a un señuelo) · wrong · missing (no dio ninguno)
                 · correct_none (no había culpable y no culpó a nadie)
                 · blamed_innocent (no había culpable y culpó a un commit)
"""

import re

from incilot_sim.injector.core import resolves

MIN_SHA = 7


def _same_commit(given: str, full: str) -> bool:
    given = given.strip().lower()
    return len(given) >= MIN_SHA and full.lower().startswith(given)


def commit_verdict(truth: dict, culprit_commit: str | None) -> str:
    culprit, decoys = truth.get("culprit_sha"), truth.get("decoy_shas") or []
    if not culprit:
        return "correct_none" if not culprit_commit else "blamed_innocent"
    if not culprit_commit:
        return "missing"
    if _same_commit(culprit_commit, culprit):
        return "correct"
    if any(_same_commit(culprit_commit, d) for d in decoys):
        return "decoy"
    return "wrong"


def score(truth: dict, diagnosis: dict) -> dict:
    action = diagnosis.get("action") or {}
    service = truth["service"]
    commit = commit_verdict(truth, diagnosis.get("culprit_commit"))
    return {
        "action_ok": resolves(truth, action.get("kind", ""), action.get("target", "")),
        "service_ok": bool(
            re.search(rf"\b{re.escape(service)}\b", diagnosis.get("service", ""), re.I)
        ),
        "commit": commit,
        "commit_ok": commit in ("correct", "correct_none"),
    }
