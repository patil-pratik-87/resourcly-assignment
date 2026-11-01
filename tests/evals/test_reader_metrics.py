from typing import Any

import pytest

from resourcly.evals.metrics import normalise_unit, score_reading, summarise_readings, unmatched


def v(page: int, value: Any, unit: str | None, kind: str, raw: str | None = None) -> dict:
    return {"page": page, "value": value, "unit": unit, "kind": kind, "raw": raw or str(value)}


def test_strict_match_needs_page_unit_kind_and_value() -> None:
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

    strict = score_reading(gold, predicted).strict

    assert (strict.gold, strict.predicted, strict.matched) == (3, 4, 1)
    assert strict.precision == 1 / 4
    assert strict.recall == 1 / 3
    assert strict.f1 == pytest.approx(2 / 7)


def test_duplicates_match_one_to_one() -> None:
    gold = [v(1, 0.75, "mm", "position")] * 2
    predicted = [v(1, 0.75, "mm", "position")] * 3

    strict = score_reading(gold, predicted).strict

    assert (strict.matched, strict.predicted) == (2, 3)


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

    assert score_reading(gold, predicted).strict.matched == 4


def test_a_unit_mismatch_is_a_miss() -> None:
    score = score_reading([v(1, 0.25, "in", "diameter")], [v(1, 0.25, "mm", "diameter")])

    assert score.strict.matched == 0


def test_records_without_a_number_match_on_their_text() -> None:
    gold = [v(1, None, None, "title_block", raw="Rev D"), v(1, None, None, "note", raw="5. UNITS")]
    predicted = [
        v(1, None, None, "title_block", raw="REV  D"),
        v(1, None, None, "note", raw="5. UNITS: MM"),
    ]

    assert score_reading(gold, predicted).strict.matched == 1


def test_counts_are_kept_per_page() -> None:
    gold = [v(1, 1.5, "mm", "linear"), v(2, 3, "mm", "linear"), v(2, 4, "mm", "linear")]
    predicted = [v(2, 3, "mm", "linear"), v(3, 9, "mm", "linear")]

    pages = score_reading(gold, predicted).pages

    assert {page: (c.gold, c.predicted, c.matched) for page, c in pages.items()} == {
        1: (1, 0, 0),
        2: (2, 1, 1),
        3: (0, 1, 0),
    }


def test_loose_match_ignores_kind_and_measures_kind_accuracy() -> None:
    gold = [
        v(1, 20, "mm", "diameter"),
        v(1, 0.2, "mm", "flatness"),
        v(1, None, None, "datum_feature", raw="A"),
    ]
    predicted = [
        v(1, 20, "mm", "diameter"),
        v(1, 0.2, "mm", "position"),
        v(2, None, None, "datum_feature", raw="A"),
    ]

    score = score_reading(gold, predicted)

    assert score.loose.matched == 2
    assert score.kind_accuracy == 1 / 2
    assert score.kind_confusion == {("diameter", "diameter"): 1, ("flatness", "position"): 1}


def test_loose_pairs_prefer_the_same_kind() -> None:
    gold = [v(1, 0.75, "mm", "position"), v(1, 0.75, "mm", "flatness")]

    score = score_reading(gold, [v(1, 0.75, "mm", "flatness")])

    assert score.kind_confusion == {("flatness", "flatness"): 1}


def test_unreadable_predictions_count_against_precision() -> None:
    gold = [v(1, 20, "mm", "diameter")]
    predicted = [
        v(1, 20, "mm", "diameter"),
        {"value": 3, "unit": "mm", "kind": "linear", "raw": "3"},
        v(1, "Ø.250", "in", "diameter"),
        "not a record",
    ]

    score = score_reading(gold, predicted)

    assert score.invalid == 3
    assert (score.strict.predicted, score.strict.matched) == (4, 1)
    assert score.loose.predicted == 4


def test_summary_pools_full_drawings_and_takes_only_recall_from_partial_gold() -> None:
    hole, slot = v(1, 20, "mm", "diameter"), v(1, 8, "mm", "linear")
    full_a = score_reading([hole, slot], [hole, v(1, 9, "mm", "linear"), v(1, 7, "mm", "linear")])
    full_b = score_reading([v(2, 5, "mm", "linear")], [v(2, 5, "mm", "radius")])
    partial = score_reading([hole, slot], [hole, *[v(1, n, "mm", "linear") for n in range(30, 40)]])

    summary = summarise_readings([("full", full_a), ("full", full_b), ("partial", partial)])

    assert summary["strict_precision"] == 1 / 4
    assert summary["strict_recall"] == 1 / 3
    assert summary["strict_f1"] == pytest.approx(2 / 7)
    assert summary["partial_recall"] == 1 / 2
    assert summary["kind_accuracy"] == 2 / 3
    assert summary["kind_confusion"] == [
        ["diameter", "diameter", 2],
        ["linear", "radius", 1],
    ]


def test_unmatched_lists_missed_gold_and_extra_predictions() -> None:
    hole, flat = v(1, 20, "mm", "diameter"), v(1, 0.2, "mm", "flatness")
    predicted = [hole, v(1, 0.2, "mm", "position"), hole, {"raw": "no page"}]

    missed, extra = unmatched([hole, flat], predicted)

    assert missed == [flat]
    assert extra == [v(1, 0.2, "mm", "position"), hole, {"raw": "no page"}]


def test_a_summary_without_full_or_partial_cases_has_no_number_for_them() -> None:
    full = score_reading([v(1, 20, "mm", "diameter")], [v(1, 20, "mm", "diameter")])

    only_full = summarise_readings([("full", full)])
    only_partial = summarise_readings([("partial", full)])

    assert only_full["partial_recall"] is None
    assert only_full["strict_f1"] == 1.0
    assert only_partial["strict_f1"] is None
    assert only_partial["partial_recall"] == 1.0


def test_a_case_with_no_loose_pair_has_no_kind_accuracy() -> None:
    score = score_reading([v(1, 20, "mm", "diameter")], [v(1, 35, "mm", "diameter")])

    assert score.kind_accuracy is None


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

    score = score_reading(gold, predicted)

    assert (score.strict.matched, score.invalid) == (0, 4)


def test_feature_accuracy_compares_feature_types_of_strict_matches() -> None:
    gold = [
        {**v(1, 0.75, "mm", "position"), "feature_id": "notch"},
        {**v(1, 0.75, "mm", "position"), "feature_id": "slot"},
        {**v(1, 20, "mm", "diameter"), "feature_id": "hole"},
        {**v(1, None, None, "title_block", raw="Rev D"), "feature_id": None},
    ]
    predicted = [
        {**v(1, 0.75, "mm", "position"), "feature_id": "c1"},
        {**v(1, 0.75, "mm", "position"), "feature_id": "c2"},
        {**v(1, 20, "mm", "diameter"), "feature_id": "c3"},
        {**v(1, None, None, "title_block", raw="Rev D"), "feature_id": None},
    ]
    gold_types = {"notch": "slot", "slot": "slot", "hole": "hole"}
    predicted_types = {"c1": "hole", "c2": "slot", "c3": "hole"}

    score = score_reading(gold, predicted, gold_types, predicted_types)

    # one position frame is typed right after pairing same types first, and the diameter is right
    assert score.feature_confusion == {
        ("slot", "slot"): 1,
        ("slot", "hole"): 1,
        ("hole", "hole"): 1,
    }
    assert score.feature_accuracy == 2 / 3


def test_feature_accuracy_is_empty_without_feature_types() -> None:
    score = score_reading([v(1, 20, "mm", "diameter")], [v(1, 20, "mm", "diameter")])

    assert score.feature_confusion == {}
    assert summarise_readings([("full", score)])["feature_accuracy"] is None


def test_feature_accuracy_is_pooled_over_cases() -> None:
    gold = [{**v(1, 20, "mm", "diameter"), "feature_id": "h"}]
    right = score_reading(gold, [{**gold[0], "feature_id": "p"}], {"h": "hole"}, {"p": "hole"})
    wrong = score_reading(gold, [{**gold[0], "feature_id": "p"}], {"h": "hole"}, {"p": "plane"})

    assert summarise_readings([("full", right), ("partial", wrong)])["feature_accuracy"] == 0.5


@pytest.mark.parametrize("feature_id", [["x"], {"a": 1}, 3, True])
def test_a_feature_id_that_is_not_a_string_counts_as_no_feature(feature_id: Any) -> None:
    gold = [{**v(1, 20, "mm", "diameter"), "feature_id": "h"}]
    predicted = [{**v(1, 20, "mm", "diameter"), "feature_id": feature_id}]

    score = score_reading(gold, predicted, {"h": "hole"}, {"x": "hole"})

    assert score.strict.matched == 1
    assert ("hole", "hole") not in score.feature_confusion


def test_a_match_without_a_predicted_feature_type_counts_as_wrong() -> None:
    gold = [
        {**v(1, 20, "mm", "diameter"), "feature_id": "h"},
        {**v(1, 0.2, "mm", "flatness"), "feature_id": "top"},
    ]
    predicted = [
        {**v(1, 20, "mm", "diameter"), "feature_id": None},
        {**v(1, 0.2, "mm", "flatness"), "feature_id": "p"},
    ]

    score = score_reading(gold, predicted, {"h": "hole", "top": "plane"}, {"p": "plane"})
    summary = summarise_readings([("full", score)])

    assert score.feature_confusion == {("hole", "(none)"): 1, ("plane", "plane"): 1}
    assert score.feature_accuracy == 0.5
    assert (summary["feature_accuracy"], summary["feature_pairs"]) == (0.5, 2)
