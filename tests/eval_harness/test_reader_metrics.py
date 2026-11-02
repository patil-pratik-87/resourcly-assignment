from typing import Any

import pytest

from resourcly.eval_harness.metrics import (
    normalise_unit,
    score_reading,
    summarise_readings,
    unmatched,
)


def scored(stratum: str, counts) -> tuple[str, dict]:
    """A case's stratum and the scores the reader suite stores for it."""
    return stratum, {"gold": counts.gold, "predicted": counts.predicted, "matched": counts.matched}


def v(page: int, value: Any, unit: str | None, kind: str, raw: str | None = None) -> dict:
    return {"page": page, "value": value, "unit": unit, "kind": kind, "raw": raw or str(value)}


def test_a_match_needs_page_unit_kind_and_value() -> None:
    gold = [
        v(1, 20, "mm", "diameter"),
        v(1, 0.2, "mm", "flatness"),
        v(1, None, None, "datum_feature", raw="A"),
    ]
    predicted = [
        v(1, 20.0, "mm", "diameter"),
        v(1, 0.2, "mm", "position"),
        v(2, None, None, "datum_feature", raw="A"),
        v(1, 35, "mm", "diameter"),
    ]

    counts = score_reading(gold, predicted)

    assert (counts.gold, counts.predicted, counts.matched) == (3, 4, 1)
    assert counts.precision == 1 / 4
    assert counts.recall == 1 / 3
    assert counts.f1 == pytest.approx(2 / 7)


def test_duplicates_match_one_to_one() -> None:
    gold = [v(1, 0.75, "mm", "position")] * 2
    predicted = [v(1, 0.75, "mm", "position")] * 3

    counts = score_reading(gold, predicted)

    assert (counts.matched, counts.predicted) == (2, 3)


def test_numbers_units_and_symbols_are_normalised_before_matching() -> None:
    gold = [
        v(1, 0.25, "in", "diameter"),
        v(1, [34.8, 35.2], "mm", "diameter"),
        v(1, 60, "deg", "angular"),
        v(2, None, None, "note", raw="⌀20 THRU −0.1"),
    ]
    predicted = [
        v(1, ".250", "inches", "Diameter"),
        v(1, ["34.80", 35.2], "MM", "diameter"),
        v(1, 60.0, "°", "angular"),
        v(2, None, "", "note", raw="  ø20   thru -0.1 "),
    ]

    assert score_reading(gold, predicted).matched == 4


def test_a_unit_mismatch_is_a_miss() -> None:
    counts = score_reading([v(1, 0.25, "in", "diameter")], [v(1, 0.25, "mm", "diameter")])

    assert counts.matched == 0


def test_records_without_a_number_match_on_their_text() -> None:
    gold = [v(1, None, None, "title_block", raw="Rev D"), v(1, None, None, "note", raw="5. UNITS")]
    predicted = [
        v(1, None, None, "title_block", raw="REV  D"),
        v(1, None, None, "note", raw="5. UNITS: MM"),
    ]

    assert score_reading(gold, predicted).matched == 1


def test_unreadable_predictions_count_against_precision() -> None:
    gold = [v(1, 20, "mm", "diameter")]
    predicted = [
        v(1, 20, "mm", "diameter"),
        {"value": 3, "unit": "mm", "kind": "linear", "raw": "3"},
        v(1, "Ø.250", "in", "diameter"),
        "not a record",
    ]

    counts = score_reading(gold, predicted)

    assert (counts.predicted, counts.matched) == (4, 1)


def test_summary_pools_full_drawings_and_takes_only_recall_from_partial_gold() -> None:
    hole, slot = v(1, 20, "mm", "diameter"), v(1, 8, "mm", "linear")
    full_a = score_reading([hole, slot], [hole, v(1, 9, "mm", "linear"), v(1, 7, "mm", "linear")])
    full_b = score_reading([v(2, 5, "mm", "linear")], [v(2, 5, "mm", "radius")])
    partial = score_reading([hole, slot], [hole, *[v(1, n, "mm", "linear") for n in range(30, 40)]])

    summary = summarise_readings(
        [scored("full", full_a), scored("full", full_b), scored("partial", partial)]
    )

    assert summary == {
        "f1": pytest.approx(2 / 7),
        "precision": 1 / 4,
        "recall": 1 / 3,
        "partial_recall": 1 / 2,
    }


def test_unmatched_lists_missed_gold_and_extra_predictions() -> None:
    hole, flat = v(1, 20, "mm", "diameter"), v(1, 0.2, "mm", "flatness")
    predicted = [hole, v(1, 0.2, "mm", "position"), hole, {"raw": "no page"}]

    missed, extra = unmatched([hole, flat], predicted)

    assert missed == [flat]
    assert extra == [v(1, 0.2, "mm", "position"), hole, {"raw": "no page"}]


def test_a_summary_without_full_or_partial_cases_has_no_number_for_them() -> None:
    full = score_reading([v(1, 20, "mm", "diameter")], [v(1, 20, "mm", "diameter")])

    only_full = summarise_readings([scored("full", full)])
    only_partial = summarise_readings([scored("partial", full)])

    assert only_full["partial_recall"] is None
    assert only_full["f1"] == 1.0
    assert only_partial["f1"] is None
    assert only_partial["partial_recall"] == 1.0


def test_unit_marks_that_ocr_and_models_emit_are_recognised() -> None:
    assert [normalise_unit(unit) for unit in ("″", "º", "˚", "ＭＭ")] == ["in", "deg", "deg", "mm"]


def test_bools_and_nan_are_not_numbers() -> None:
    gold = [v(1, 1, "mm", "diameter")]
    predicted = [
        v(1, True, "mm", "diameter"),
        {**v(1, 1, "mm", "diameter"), "page": True},
        v(1, float("nan"), "mm", "diameter"),
        v(1, "inf", "mm", "diameter"),
    ]

    counts = score_reading(gold, predicted)

    assert (counts.matched, counts.predicted) == (0, 4)
