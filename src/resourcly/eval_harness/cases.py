import hashlib
import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from resourcly.bootstrap import Services
from resourcly.eval_harness import gold_rules

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


# A row's label is the route the router should give it; "other" items fit no case.
ROUTES = ("drawing", "photo", "text", "other")
ROUTE_FIELDS = ("id", "label", "unit")


def route_cases(services: Services, split: str) -> list[Case]:
    """One case per labelled item of evals/gold/routes.jsonl, stratified by its expected route.

    A router split names units, the sources it keeps whole, and takes every case of those units.
    A case's gold adds `expected_route` and `input`, the request to send: the item's text and the
    file it names. A message sent with a file names that item in `attachment`. A row that
    `evals check` reports as broken is skipped with a warning.
    """
    splits = _splits(services, "router", split)
    rows, problems = _route_rows(services.gold.route_cases())
    for problem in problems:
        log.warning("router %s; skipped", problem)
    by_id = {row["id"]: row for row in rows}
    cases = []
    for row, name in _in_split(rows, splits, split):
        attached = by_id[row["attachment"]] if row.get("attachment") else row
        gold = {
            **row,
            "expected_route": row["label"],
            "input": {"text": row.get("text"), "file": attached.get("file")},
        }
        cases.append(Case(row["id"], name, row["label"], gold))
    return sorted(cases, key=lambda case: case.case_id)


def _route_rows(rows: list[Any]) -> tuple[list[dict[str, Any]], list[str]]:
    """The sound router rows, and what is wrong with each of the others."""
    by_id = {row["id"]: row for row in rows if isinstance(row, dict) and "id" in row}
    sound, problems = [], []
    for number, row in enumerate(rows, start=1):
        missing = [name for name in ROUTE_FIELDS if not isinstance(row, dict) or name not in row]
        if missing:
            problems.append(f"routes.jsonl line {number} lacks {', '.join(missing)}")
        elif row["label"] not in ROUTES:
            problems.append(
                f"{row['id']} has label '{row['label']}';"
                " use drawing, photo, text or other (fits no case)"
            )
        elif row.get("attachment") and row["attachment"] not in by_id:
            problems.append(
                f"{row['id']} sends the file of '{row['attachment']}', which is not a case"
            )
        else:
            sound.append(row)
    return sound, problems


FAILURE_KINDS = ("positive", "negative_drawing", "negative_unrelated")
FAILURE_FIELDS = ("case_id", "image", "kind", "unit")
# what a photo of a report figure must say about the figure it shows
EXPECTED_FIELDS = ("expected_report", "expected_figure", "section", "failure_mode")


def failure_cases(services: Services, split: str) -> list[Case]:
    """One case per row of evals/gold/failure/cases.jsonl, stratified by its kind.

    A failure split names units, a report figure with all its copies or one negative, and takes
    every case of those units. A row that `evals check` reports as broken is skipped with a
    warning.
    """
    splits = _splits(services, "failure", split)
    rows, problems = _failure_rows(services.gold.failure_cases())
    for problem in problems:
        log.warning("failure %s; skipped", problem)
    cases = [
        Case(row["case_id"], name, row["kind"], row) for row, name in _in_split(rows, splits, split)
    ]
    return sorted(cases, key=lambda case: case.case_id)


def _failure_rows(rows: list[Any]) -> tuple[list[dict[str, Any]], list[str]]:
    """The sound failure rows, and what is wrong with each of the others."""
    sound, problems = [], []
    for number, row in enumerate(rows, start=1):
        missing = [
            name for name in FAILURE_FIELDS if not isinstance(row, dict) or not row.get(name)
        ]
        expected = [name for name in EXPECTED_FIELDS if not missing and not row.get(name)]
        if missing:
            problems.append(f"cases.jsonl line {number} lacks {', '.join(missing)}")
        elif row["kind"] not in FAILURE_KINDS:
            problems.append(
                f"{row['case_id']} has kind '{row['kind']}';"
                " use positive, negative_drawing or negative_unrelated"
            )
        elif row["kind"] == "positive" and expected:
            problems.append(f"{row['case_id']} lacks {', '.join(expected)}")
        else:
            sound.append(row)
    return sound, problems


def _in_split(
    rows: list[dict[str, Any]], splits: dict[str, list[str]], split: str
) -> list[tuple[dict[str, Any], str]]:
    """Each row of the split, with the split its unit is in; "all" takes every row."""
    split_of = {unit: name for name, units in splits.items() for unit in units}
    named = [(row, split_of.get(row["unit"], "unsplit")) for row in rows]
    return [(row, name) for row, name in named if split == "all" or name == split]


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


def check_gold(services: Services, components: Iterable[str]) -> list[tuple[str, str]]:
    """(level, message) pairs about the gold and splits; level is ok, warning or error.

    `components` are those with a suite; splits.toml naming another is a warning.

    Each drawing's gold goes through the package models, then, once they accept it, the rules in
    gold_rules, so one bad field is reported once. The router and failure gold go through their
    row checks, and every split through the split checks.
    """
    splits = services.gold.splits()
    found: list[tuple[str, str]] = []
    for component in sorted(splits.keys() - set(components)):
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
    _check_routes(services, _split_of("router", splits.get("router", {}), found), found)
    _check_failures(services, _split_of("failure", splits.get("failure", {}), found), found)
    return found


def _check_routes(
    services: Services, split_of: dict[str, str], found: list[tuple[str, str]]
) -> None:
    raw = services.gold.route_cases()
    rows, problems = _route_rows(raw)
    found.extend(("error", f"router {problem}") for problem in problems)
    for case_id in _duplicates(raw, "id"):
        found.append(("error", f"router case id {case_id} is used more than once"))
    found.extend(("error", f"router {leak}") for leak in _unit_leaks(rows))
    units = {row["unit"] for row in rows}
    if rows:
        found.append(("ok", f"router {len(rows)} case(s) in {len(units)} unit(s)"))
    files = {f"routes/{row['file']}" for row in rows if row.get("file")}
    _absent("router", services, files, found)
    _unmatched("router", split_of, units, found)


def _check_failures(
    services: Services, split_of: dict[str, str], found: list[tuple[str, str]]
) -> None:
    raw = services.gold.failure_cases()
    rows, problems = _failure_rows(raw)
    found.extend(("error", f"failure {problem}") for problem in problems)
    for case_id in _duplicates(raw, "case_id"):
        found.append(("error", f"failure case id {case_id} is used more than once"))
    if rows:
        photos = sum(1 for row in rows if row["kind"] == "positive")
        found.append(
            (
                "ok",
                f"failure {len(rows)} case(s): {photos} photo(s), {len(rows) - photos} negative(s)",
            )
        )
    _absent("failure", services, {f"failure/{row['image']}" for row in rows}, found)
    _unmatched("failure", split_of, {row["unit"] for row in rows}, found)


def _duplicates(rows: list[Any], key: str) -> list[str]:
    ids = [row[key] for row in rows if isinstance(row, dict) and row.get(key)]
    return sorted({i for i in ids if ids.count(i) > 1})


def _absent(
    component: str, services: Services, files: set[str], found: list[tuple[str, str]]
) -> None:
    absent = sum(1 for file in files if not services.gold.file_exists(file))
    if absent:
        found.append(
            (
                "warning",
                f"{component} {absent} of {len(files)} file(s) are missing;"
                " they are committed, so restore them from git",
            )
        )


def _unit_leaks(rows: list[dict[str, Any]]) -> list[str]:
    """Rows that a split could put on two sides: a group whose items are in different units, and
    a message whose file is in another unit than the message."""
    by_id = {row["id"]: row for row in rows}
    units_of: dict[str, set[str]] = {}
    for row in rows:
        units_of.setdefault(row.get("group", row["unit"]), set()).add(row["unit"])
    leaks = [
        f"group {group} spans units {', '.join(sorted(units))}"
        for group, units in sorted(units_of.items())
        if len(units) > 1
    ]
    for row in rows:
        attached = by_id.get(row.get("attachment") or "")
        if attached and attached["unit"] != row["unit"]:
            leaks.append(
                f"{row['id']} is in unit {row['unit']} but its file {attached['id']}"
                f" is in {attached['unit']}"
            )
    return leaks


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
