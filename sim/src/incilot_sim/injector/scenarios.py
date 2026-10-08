"""Fault scenarios defined in incilot-data/scenarios/*.toml."""

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
    infra: dict
    ground_truth: dict
    split: str  # dev: for developing the agent; exam: only for measuring it


def authors(data: Path) -> dict[str, str]:
    """The company's fictional authors (history.toml), by key."""
    return tomllib.loads((data / "history.toml").read_text())["authors"]


def load(data: Path) -> dict[str, list[Variant]]:
    """Scenarios by id. Culprit commit authors are resolved via history.toml."""
    authors_by_key = authors(data)
    scenarios = {}
    for path in sorted((data / "scenarios").glob("*.toml")):
        spec = tomllib.loads(path.read_text())
        variants = []
        for v in spec["variants"]:
            culprit = v.get("culprit")
            if culprit:
                culprit = culprit | {"author": authors_by_key[culprit["author"]]}
            variants.append(
                Variant(
                    scenario=spec["id"],
                    id=v["id"],
                    title=spec["title"],
                    category=spec["category"],
                    service=v["service"],
                    culprit=culprit,
                    faults=v.get("faults", {}),
                    infra=v.get("infra", {}),
                    ground_truth=v["ground_truth"],
                    split=v.get("split", "dev"),
                )
            )
        scenarios[spec["id"]] = variants
    return scenarios


def pick(scenarios: dict[str, list[Variant]], scenario: str, variant: str | None = None) -> Variant:
    """A specific variant, or a random one if none is given."""
    if scenario not in scenarios:
        raise KeyError(f"unknown scenario: {scenario}")
    variants = scenarios[scenario]
    if variant is None:
        return random.choice(variants)
    for v in variants:
        if v.id == variant:
            return v
    raise KeyError(f"unknown variant: {scenario}/{variant}")
