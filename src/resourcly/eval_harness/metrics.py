"""Pure scoring functions: records and labels in, numbers out. No files, models or network."""

import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
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


def score_reading(gold: list[Record], predicted: list[Record]) -> Counts:
    """Gold, predicted and matched records; a match needs the same page, unit, kind and value.

    A record with no number uses its normalised raw text in place of the value. A predicted record
    that cannot be read (no page, a value that is not a number) is invalid: it counts as a
    prediction and never matches.
    """
    gold_keys = Counter(_key(record) for record in gold)
    readable = [key for record in predicted if (key := _readable_key(record)) is not None]
    predicted_keys = Counter(readable)
    invalid = len(predicted) - len(readable)
    return Counts(
        gold_keys.total(),
        predicted_keys.total() + invalid,
        (gold_keys & predicted_keys).total(),
    )


def unmatched(gold: list[Record], predicted: list[Record]) -> tuple[list[Record], list[Record]]:
    """The gold records no prediction matched, and the predictions that matched none."""
    gold_keys = [_key(record) for record in gold]
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
        key = _key(record)
    except (KeyError, TypeError, ValueError):
        return None
    page = key[0]
    return key if isinstance(page, int) and not isinstance(page, bool) else None


def _key(record: Record) -> tuple:
    value = normalise_value(record["value"])
    content = normalise_raw(record["raw"]) if value is None else value
    return record["page"], normalise_unit(record["unit"]), _kind(record["kind"]), content


def summarise_readings(cases: list[tuple[str, Counts]]) -> dict[str, Any]:
    """Micro averages: F1, precision and recall over full drawings, recall only over partial gold.

    Partial gold lists a few values per drawing, so a prediction missing from it may still be right.
    A metric with no case to measure it on is None, not zero.
    """
    full = sum((counts for stratum, counts in cases if stratum == "full"), Counts())
    partial = [counts for stratum, counts in cases if stratum == "partial"]
    measured = any(stratum == "full" for stratum, _ in cases)
    return {
        "f1": full.f1 if measured else None,
        "precision": full.precision if measured else None,
        "recall": full.recall if measured else None,
        "partial_recall": sum(partial, Counts()).recall if partial else None,
    }


LABELLED_ROUTES = ("drawing", "photo", "text")
OTHER = "other"
FAILED = "(error)"


@dataclass(frozen=True)
class RouteOutcome:
    """One routed case; route is None when the call failed."""

    case_id: str
    expected: str
    route: str | None
    layer: str | None
    reason: str | None


def summarise_routes(outcomes: list[RouteOutcome]) -> dict[str, Any]:
    """How well a router picked the case, and every case it got wrong.

    Accuracy covers the labelled requests: those whose case is drawing, photo or text. Drawing
    recall is the share of drawings sent to the reader. The other files fit no case, and whether
    they should is a product choice, so they are scored apart as the share the router kept out
    (routed to other). A metric with nothing to measure is None.
    """
    labelled = [o for o in outcomes if o.expected in LABELLED_ROUTES]
    drawings = [o for o in labelled if o.expected == "drawing"]
    other = [o for o in outcomes if o.expected == OTHER]
    return {
        "accuracy": _share(labelled, lambda o: o.route == o.expected),
        "drawing_recall": _share(drawings, lambda o: o.route == "drawing"),
        "other_kept_out": _share(other, lambda o: o.route == OTHER),
        "mistakes": [
            _row(o) for o in sorted(outcomes, key=lambda o: o.case_id) if o.route != o.expected
        ],
    }


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

    A photo of a report figure scores section@1 on whether the top figure is in the right report
    section, and mode@3 on whether one of the top three shows its failure mode. A negative, a photo
    no report covers, scores kept_out: 1 when no figure came back. A failed call keeps nothing out.
    """
    if gold["kind"] != PHOTO:
        return {"kept_out": float(figures == [])}
    ranked = [f for f in figures or [] if isinstance(f, dict)]
    top = ranked[0] if ranked else {}
    return {
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
        "section@1": mean(photos, "section@1"),
        "mode@3": mean(photos, "mode@3"),
        "kept_out": mean(negatives, "kept_out"),
    }
