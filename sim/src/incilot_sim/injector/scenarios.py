"""Escenarios de fallo definidos en incilot-data/scenarios/*.toml."""

import random
import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Variant:
    scenario: str
    id: str
    title: str
    category: str
    service: str
    culprit: dict | None
    faults: dict[str, dict]
    ground_truth: dict


def load(data: Path) -> dict[str, list[Variant]]:
    """Escenarios por id. Los autores de los commits culpables se resuelven con history.toml."""
    authors = tomllib.loads((data / "history.toml").read_text())["authors"]
    scenarios = {}
    for path in sorted((data / "scenarios").glob("*.toml")):
        spec = tomllib.loads(path.read_text())
        variants = []
        for v in spec["variants"]:
            culprit = v.get("culprit")
            if culprit:
                culprit = culprit | {"author": authors[culprit["author"]]}
            variants.append(
                Variant(
                    scenario=spec["id"],
                    id=v["id"],
                    title=spec["title"],
                    category=spec["category"],
                    service=v["service"],
                    culprit=culprit,
                    faults=v.get("faults", {}),
                    ground_truth=v["ground_truth"],
                )
            )
        scenarios[spec["id"]] = variants
    return scenarios


def pick(scenarios: dict[str, list[Variant]], scenario: str, variant: str | None = None) -> Variant:
    """Una variante concreta, o una al azar si no se indica."""
    if scenario not in scenarios:
        raise KeyError(f"escenario desconocido: {scenario}")
    variants = scenarios[scenario]
    if variant is None:
        return random.choice(variants)
    for v in variants:
        if v.id == variant:
            return v
    raise KeyError(f"variante desconocida: {scenario}/{variant}")
