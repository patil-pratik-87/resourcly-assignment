"""Pure scoring functions: records and labels in, numbers out. No files, models or network."""

import math
import re
import statistics
import unicodedata
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

Record = dict[str, Any]

UNITS = {
    "mm": "mm",
    "millimeter": "mm",
    "millimeters": "mm",
    "millimetre": "mm",
    "millimetres": "mm",
    "in": "in",
    "inch": "in",
    "inches": "in",
    '"': "in",
    "deg": "deg",
    "degree": "deg",
    "degrees": "deg",
    "°": "deg",
}
UNIT_MARKS = str.maketrans({"º": "°", "˚": "°", "″": '"'})
NO_FEATURE = "(none)"
SYMBOLS = str.maketrans({"ø": "⌀", "∅": "⌀", "−": "-", "–": "-", "—": "-", "‐": "-"})


@dataclass(frozen=True)
class Counts:
    gold: int = 0
    predicted: int = 0
    matched: int = 0

    @property
    def precision(self) -> float:
        return self.matched / self.predicted if self.predicted else 0.0

    @property
    def recall(self) -> float:
        return self.matched / self.gold if self.gold else 0.0

    @property
    def f1(self) -> float:
        total = self.precision + self.recall
        return 2 * self.precision * self.recall / total if total else 0.0

    def __add__(self, other: "Counts") -> "Counts":
        return Counts(
            self.gold + other.gold,
            self.predicted + other.predicted,
            self.matched + other.matched,
        )


@dataclass(frozen=True)
class ReadingScore:
    """Strict matches key on page, unit, kind and value; loose matches leave kind out.

    A record with no number uses its normalised raw text in place of the value. A predicted record
    that cannot be read (no page, a value that is not a number) is invalid: it counts as a
    prediction and never matches.
    """

    strict: Counts
    pages: dict[int, Counts]
    loose: Counts
    kind_confusion: dict[tuple[str, str], int]
    invalid: int
    feature_confusion: dict[tuple[str, str], int] = field(default_factory=dict)

    @property
    def kind_accuracy(self) -> float | None:
        """The share of loose pairs with the same kind; None when nothing matched loosely."""
        return _kind_accuracy(self.kind_confusion)

    @property
    def feature_accuracy(self) -> float | None:
        """The share of typed strict pairs with the same feature type; None when there are none."""
        return _kind_accuracy(self.feature_confusion)


def score_reading(
    gold: list[Record],
    predicted: list[Record],
    gold_features: dict[str, str] | None = None,
    predicted_features: dict[str, str] | None = None,
) -> ReadingScore:
    """Strict, page and loose counts, kind confusion, and feature confusion given feature types.

    `gold_features` and `predicted_features` map each side's feature ids to feature types.
    Feature accuracy pairs strictly matched records, same type first, and compares the types of
    the features they belong to. A gold record whose feature has no type, such as a title block
    entry, is left out; a matched prediction without a typed feature counts as wrong.
    """
    gold_keys = Counter(_strict_key(record) for record in gold)
    readable = [key for record in predicted if (key := _readable_key(record)) is not None]
    predicted_keys = Counter(readable)
    invalid = len(predicted) - len(readable)
    pages = {
        page: _counts(
            Counter({k: n for k, n in gold_keys.items() if k[0] == page}),
            Counter({k: n for k, n in predicted_keys.items() if k[0] == page}),
        )
        for page in sorted({key[0] for key in gold_keys | predicted_keys})
    }
    return ReadingScore(
        strict=_counts(gold_keys, predicted_keys, invalid),
        pages=pages,
        loose=_counts(_loose(gold_keys), _loose(predicted_keys), invalid),
        kind_confusion=_kind_pairs(gold_keys, predicted_keys),
        invalid=invalid,
        feature_confusion=_feature_pairs(
            gold, predicted, gold_features or {}, predicted_features or {}
        ),
    )


def _feature_pairs(
    gold: list[Record],
    predicted: list[Record],
    gold_types: dict[str, str],
    predicted_types: dict[str, str],
) -> dict[tuple[str, str], int]:
    """Feature type pairs on strict matches whose gold value has a typed feature.

    A matched prediction without a typed feature pairs as NO_FEATURE, so it counts as wrong.
    """
    groups: dict[tuple, tuple[Counter, Counter]] = {}
    for record in gold:
        key, kind = _readable_key(record), gold_types.get(_feature_id(record))
        if key is not None and kind is not None:
            groups.setdefault(key, (Counter(), Counter()))[0][kind] += 1
    for record in predicted:
        key = _readable_key(record)
        if key in groups:
            groups[key][1][predicted_types.get(_feature_id(record), NO_FEATURE)] += 1
    return _paired(groups.values())


def _feature_id(record: Any) -> str | None:
    """The record's feature id, or None when it has none or it is not a string."""
    feature_id = record.get("feature_id") if isinstance(record, dict) else None
    return feature_id if isinstance(feature_id, str) else None


def unmatched(gold: list[Record], predicted: list[Record]) -> tuple[list[Record], list[Record]]:
    """The gold records no prediction strictly matched, and the predictions that matched none."""
    gold_keys = [_strict_key(record) for record in gold]
    predicted_keys = [_readable_key(record) for record in predicted]
    budget = Counter(gold_keys) & Counter(key for key in predicted_keys if key is not None)
    return _leftover(gold, gold_keys, budget.copy()), _leftover(predicted, predicted_keys, budget)


def _leftover(records: list[Record], keys: list[tuple | None], budget: Counter) -> list[Record]:
    left = []
    for record, key in zip(records, keys, strict=True):
        if key is not None and budget[key] > 0:
            budget[key] -= 1
        else:
            left.append(record)
    return left


def _counts(gold: Counter, predicted: Counter, invalid: int = 0) -> Counts:
    return Counts(gold.total(), predicted.total() + invalid, (gold & predicted).total())


def _loose(keys: Counter) -> Counter:
    loose: Counter = Counter()
    for (page, unit, _, content), n in keys.items():
        loose[page, unit, content] += n
    return loose


def _kind_pairs(gold: Counter, predicted: Counter) -> dict[tuple[str, str], int]:
    """Pairs records that match loosely, same kind first, and counts (gold kind, predicted kind)."""
    groups: dict[tuple, tuple[Counter, Counter]] = {}
    for side, keys in ((0, gold), (1, predicted)):
        for (page, unit, kind, content), n in keys.items():
            groups.setdefault((page, unit, content), (Counter(), Counter()))[side][kind] += n
    return _paired(groups.values())


def _paired(groups: Iterable[tuple[Counter, Counter]]) -> dict[tuple[str, str], int]:
    """(gold label, predicted label) counts within each group, pairing equal labels first."""
    pairs: Counter = Counter()
    for gold_kinds, predicted_kinds in groups:
        same = gold_kinds & predicted_kinds
        pairs.update({(kind, kind): n for kind, n in same.items()})
        rest = zip(
            sorted((gold_kinds - same).elements()),
            sorted((predicted_kinds - same).elements()),
            strict=False,
        )
        pairs.update(rest)
    return dict(sorted(pairs.items()))


def normalise_raw(text: str) -> str:
    """Casefolded, one diameter sign, one minus sign and single spaces."""
    folded = unicodedata.normalize("NFKC", text).casefold().translate(SYMBOLS)
    return " ".join(folded.split())


def normalise_unit(unit: str | None) -> str | None:
    """A known unit as mm, in or deg. Marks OCR gives for degrees and inches are mapped first,
    because NFKC would turn the ordinal sign "º" into the letter "o"."""
    text = unicodedata.normalize("NFKC", (unit or "").translate(UNIT_MARKS))
    folded = text.strip().casefold().rstrip(".")
    if folded in ("", "none"):
        return None
    return UNITS.get(folded, folded)


def normalise_value(value: Any) -> tuple[float, ...] | None:
    """A number or [lower, upper] as rounded floats; numbers may arrive as text such as ".250"."""
    if value is None:
        return None
    items = value if isinstance(value, list | tuple) else [value]
    return tuple(_number(item) for item in items)


def _number(item: Any) -> float:
    """A finite number; a bool, NaN or infinity is refused, so the record is unreadable."""
    if isinstance(item, bool):
        raise TypeError("a bool is not a number")
    number = float(item)
    if not math.isfinite(number):
        raise ValueError(f"{item!r} is not a finite number")
    return round(number, 6)


def _kind(kind: Any) -> str:
    return re.sub(r"[\s-]+", "_", str(kind or "").strip().casefold())


def _readable_key(record: Any) -> tuple | None:
    try:
        key = _strict_key(record)
    except (KeyError, TypeError, ValueError):
        return None
    page = key[0]
    return key if isinstance(page, int) and not isinstance(page, bool) else None


def _strict_key(record: Record) -> tuple:
    value = normalise_value(record["value"])
    content = normalise_raw(record["raw"]) if value is None else value
    return record["page"], normalise_unit(record["unit"]), _kind(record["kind"]), content


def summarise_readings(cases: list[tuple[str, ReadingScore]]) -> dict[str, Any]:
    """Micro averages: strict and loose scores over full drawings, recall only over partial gold.

    Partial gold lists a few values per drawing, so a prediction missing from it may still be right.
    A metric with no case to measure it on is None, not zero.
    """
    full = [score for stratum, score in cases if stratum == "full"]
    partial = [score for stratum, score in cases if stratum == "partial"]
    strict = sum((score.strict for score in full), Counts())
    loose = sum((score.loose for score in full), Counts())
    confusion: Counter = Counter()
    features: Counter = Counter()
    for _, score in cases:
        confusion.update(score.kind_confusion)
        features.update(score.feature_confusion)
    partial_recall = sum((score.strict for score in partial), Counts()).recall
    return {
        "strict_f1": strict.f1 if full else None,
        "strict_precision": strict.precision if full else None,
        "strict_recall": strict.recall if full else None,
        "loose_f1": loose.f1 if full else None,
        "partial_recall": partial_recall if partial else None,
        "kind_accuracy": _kind_accuracy(confusion),
        "feature_accuracy": _kind_accuracy(features),
        "feature_pairs": sum(features.values()),
        "invalid_records": sum(score.invalid for _, score in cases),
        "kind_confusion": [[*pair, n] for pair, n in sorted(confusion.items())],
        "feature_confusion": [[*pair, n] for pair, n in sorted(features.items())],
    }


def _kind_accuracy(confusion: dict[tuple[str, str], int]) -> float | None:
    pairs = sum(confusion.values())
    right = sum(n for (gold, predicted), n in confusion.items() if gold == predicted)
    return right / pairs if pairs else None


LABELLED_ROUTES = ("drawing", "photo", "text")
OTHER = "other"
FAILED = "(error)"


@dataclass(frozen=True)
class RouteOutcome:
    """One routed case. route is None when the call failed; elapsed_ms is the router's own time."""

    case_id: str
    expected: str
    route: str | None
    layer: str | None
    reason: str | None
    elapsed_ms: float | None
    attached: bool


def summarise_routes(outcomes: list[RouteOutcome]) -> dict[str, Any]:
    """How well a router picked the case, what each layer decided, and what it cost.

    Accuracy and the recall of each route cover the labelled requests: those whose case is drawing,
    photo or text. The other files fit no case, and whether they should is a product choice, so
    they are scored apart as the share the router kept out (routed to other), and those it sent
    to a real case, which would reach that case's reader, are listed in other_misrouted. The
    escalation rate and the median time cover the labelled requests with a file, since a text
    question is always decided by its first rule. Escalation is the share decided by the vlm
    layer. A metric with nothing to measure is None.
    """
    labelled = [o for o in outcomes if o.expected in LABELLED_ROUTES]
    attached = [o for o in labelled if o.attached]
    other = [o for o in outcomes if o.expected == OTHER]
    summary: dict[str, Any] = {
        "cases": len(outcomes),
        "accuracy": _share(labelled, lambda o: o.route == o.expected),
    }
    for route in LABELLED_ROUTES:
        wanted = [o for o in labelled if o.expected == route]
        summary[f"{route}_recall"] = _share(wanted, lambda o, r=route: o.route == r)
    summary["other_cases"] = len(other)
    summary["other_kept_out"] = _share(other, lambda o: o.route == OTHER)
    summary["escalation_rate"] = _share(attached, lambda o: o.layer == "vlm")
    times = [o.elapsed_ms for o in attached if o.elapsed_ms is not None]
    summary["median_ms"] = statistics.median(times) if times else None
    by_id = sorted(outcomes, key=lambda o: o.case_id)
    summary["mistakes"] = [
        _row(o) for o in by_id if o.expected in LABELLED_ROUTES and o.route != o.expected
    ]
    summary["other_misrouted"] = [
        _row(o) for o in by_id if o.expected == OTHER and o.route in LABELLED_ROUTES
    ]
    confusion: dict[str, Counter] = {}
    for o in outcomes:
        confusion.setdefault(o.expected, Counter())[o.route or FAILED] += 1
    summary["confusion"] = {
        expected: dict(sorted(cells.items())) for expected, cells in sorted(confusion.items())
    }
    return summary


def _share(items: list[RouteOutcome], keep: Any) -> float | None:
    return sum(1 for item in items if keep(item)) / len(items) if items else None


def _row(outcome: RouteOutcome) -> dict[str, Any]:
    return {
        "case": outcome.case_id,
        "expected": outcome.expected,
        "got": outcome.route or FAILED,
        "layer": outcome.layer or "-",
        "reason": outcome.reason,
    }


PHOTO = "positive"


def score_failure(gold: dict[str, Any], figures: list[Any] | None) -> dict[str, float]:
    """How well the ranked figures answer one case; figures is None when the call failed.

    A photo of a report figure scores report@1 and section@1 on the top figure, and mode@3 on
    whether one of the top three shows its failure mode. A negative, a photo no report covers,
    scores kept_out: 1 when no figure came back. A failed call keeps nothing out.
    """
    if gold["kind"] != PHOTO:
        return {"kept_out": float(figures == [])}
    ranked = [f for f in figures or [] if isinstance(f, dict)]
    top = ranked[0] if ranked else {}
    return {
        "report@1": float(top.get("report") == gold["expected_report"]),
        "section@1": float(
            (top.get("report"), top.get("section")) == (gold["expected_report"], gold["section"])
        ),
        "mode@3": float(any(f.get("failure_mode") == gold["failure_mode"] for f in ranked[:3])),
    }


def summarise_failures(scores: list[tuple[str, dict[str, float]]]) -> dict[str, Any]:
    """Means over the photos of report figures, and the share of negatives kept out."""
    photos = [score for kind, score in scores if kind == PHOTO]
    negatives = [score for kind, score in scores if kind != PHOTO]

    def mean(rows: list[dict[str, float]], name: str) -> float | None:
        return sum(row[name] for row in rows) / len(rows) if rows else None

    return {
        "cases": len(scores),
        "photos": len(photos),
        "negatives": len(negatives),
        "report@1": mean(photos, "report@1"),
        "section@1": mean(photos, "section@1"),
        "mode@3": mean(photos, "mode@3"),
        "kept_out": mean(negatives, "kept_out"),
    }
