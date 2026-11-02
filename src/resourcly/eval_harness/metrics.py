"""Pure scoring functions: records and labels in, numbers out. No files, models or network."""

import math
import re
import unicodedata
from collections import Counter
from collections.abc import Callable
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
SYMBOLS = str.maketrans({"ø": "⌀", "∅": "⌀", "−": "-", "–": "-", "\u2014": "-", "‐": "-"})


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


Scored = list[tuple[str, dict[str, Any]]]  # each case's stratum and its stored scores


def summarise_readings(cases: Scored) -> dict[str, Any]:
    """Micro averages: F1, precision and recall over full drawings, recall only over partial gold.

    Partial gold lists a few values per drawing, so a prediction missing from it may still be right.
    A metric with no case to measure it on is None, not zero.
    """
    full = [_counts(scores) for stratum, scores in cases if stratum == "full"]
    partial = [_counts(scores) for stratum, scores in cases if stratum == "partial"]
    total = sum(full, Counts())
    return {
        "f1": total.f1 if full else None,
        "precision": total.precision if full else None,
        "recall": total.recall if full else None,
        "partial_recall": sum(partial, Counts()).recall if partial else None,
    }


def _counts(scores: dict[str, Any]) -> Counts:
    return Counts(scores["gold"], scores["predicted"], scores["matched"])


LABELLED_ROUTES = ("drawing", "photo", "text")


def summarise_routes(cases: Scored) -> dict[str, Any]:
    """How well a router picked the case; each case's stratum is the route it should get.

    Accuracy covers the labelled requests: those whose case is drawing, photo or text. Drawing
    recall is the share of drawings sent to the reader. The other files fit no case, and whether
    they should is a product choice, so they are scored apart as the share the router kept out
    (routed to other). A metric with nothing to measure is None.
    """
    return {
        "accuracy": _mean(cases, "correct", lambda stratum: stratum in LABELLED_ROUTES),
        "drawing_recall": _mean(cases, "correct", lambda stratum: stratum == "drawing"),
        "other_kept_out": _mean(cases, "correct", lambda stratum: stratum == "other"),
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


def summarise_failures(cases: Scored) -> dict[str, Any]:
    """Means over the photos of report figures, and the share of negatives kept out."""
    return {
        "section@1": _mean(cases, "section@1", lambda stratum: stratum == PHOTO),
        "mode@3": _mean(cases, "mode@3", lambda stratum: stratum == PHOTO),
        "kept_out": _mean(cases, "kept_out", lambda stratum: stratum != PHOTO),
    }


def _mean(cases: Scored, name: str, keep: Callable[[str], bool]) -> float | None:
    """The mean of one score over the cases whose stratum `keep` accepts; None for no case."""
    values = [scores[name] for stratum, scores in cases if keep(stratum)]
    return sum(values) / len(values) if values else None
