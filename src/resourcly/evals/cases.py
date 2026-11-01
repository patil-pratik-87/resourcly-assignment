import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Any

from resourcly.bootstrap import Services
from resourcly.evals import gold_rules

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Case:
    case_id: str
    split: str
    stratum: str
    gold: Any

    @property
    def gold_hash(self) -> str:
        text = json.dumps(self.gold, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(text.encode()).hexdigest()[:12]


def reader_cases(services: Services, split: str) -> list[Case]:
    """One case per drawing gold file: "full" from drawings/, "partial" from partial/.

    "all" takes every gold file, also those no split names. A drawing the split names without a
    gold file, or with a gold file that fails its checks, is skipped with a warning. Under "all"
    only the second warns, since "all" means the gold files that exist.
    """
    splits = _splits(services, "reader", split)
    split_of = {drawing: name for name, drawings in splits.items() for drawing in drawings}
    gold = {row.drawing: row.source for row in services.gold.list_drawings() if row.has_gold}
    wanted = sorted(gold) if split == "all" else splits.get(split, [])
    issues = services.gold.check_all()
    cases = []
    for drawing in sorted(wanted):
        if drawing not in gold:
            log.warning("%s has no gold file; skipped", drawing)
        elif issues[drawing]:
            log.warning("%s gold has %d issue(s); skipped", drawing, len(issues[drawing]))
        else:
            stratum = "full" if gold[drawing] == "drawings" else "partial"
            document = services.gold.load(drawing)
            cases.append(Case(drawing, split_of.get(drawing, "unsplit"), stratum, document))
    return cases


def _splits(services: Services, component: str, split: str) -> dict[str, list[str]]:
    """The component's splits from splits.toml; a split it does not name is refused."""
    splits = services.gold.splits().get(component, {})
    if split != "all" and split not in splits:
        names = ", ".join(sorted(splits)) + " or all" if splits else "all"
        raise LookupError(f"no {component} split '{split}'; use {names}")
    return splits


def check_gold(services: Services) -> list[tuple[str, str]]:
    """(level, message) pairs about the gold and splits; level is ok, warning or error.

    Each drawing's gold goes through the package models, then, once they accept it, the rules in
    gold_rules, so one bad field is reported once, and the splits through the split checks.
    """
    splits = services.gold.splits()
    found: list[tuple[str, str]] = []
    for component in sorted(splits.keys() - {"reader"}):
        found.append(("warning", f"splits.toml names an unknown component '{component}'"))
    sources = {row.drawing: row.source for row in services.gold.list_drawings() if row.has_gold}
    issues = services.gold.check_all()
    reader = _split_of("reader", splits.get("reader", {}), found)
    for drawing, source in sorted(sources.items()):
        stratum = "full" if source == "drawings" else "partial"
        problems = [
            f"{'.'.join(str(part) for part in issue.loc) or '(document)'}: {issue.message}"
            for issue in issues[drawing]
        ]
        warnings: list[str] = []
        if not problems:
            document = services.gold.load(drawing)
            problems, warnings = gold_rules.validate(document)
        found.extend(("error", f"reader {drawing} gold: {problem}") for problem in problems)
        found.extend(("warning", f"reader {drawing} gold: {warning}") for warning in warnings)
        if not problems:
            split = reader.get(drawing, "no split")
            tally = gold_rules.tally(document)
            found.append(("ok", f"reader {drawing} ({stratum}, {split}): {tally}"))
    _unmatched("reader", reader, set(sources), found)
    return found


def _split_of(
    component: str, splits: dict[str, list[str]], found: list[tuple[str, str]]
) -> dict[str, str]:
    named: dict[str, list[str]] = {}
    for split, ids in splits.items():
        for case_id in ids:
            named.setdefault(case_id, []).append(split)
    for case_id, names in sorted(named.items()):
        if len(names) > 1:
            found.append(
                ("error", f"{component} {case_id} is in more than one split: {', '.join(names)}")
            )
    return {case_id: names[0] for case_id, names in named.items()}


def _unmatched(
    component: str, split_of: dict[str, str], gold: set[str], found: list[tuple[str, str]]
) -> None:
    for case_id in sorted(split_of.keys() - gold):
        found.append(
            (
                "warning",
                f"{component} {case_id} is in the {split_of[case_id]} split but has no gold",
            )
        )
    for case_id in sorted(gold - split_of.keys()):
        found.append(("warning", f"{component} {case_id} has gold but is in no split"))
