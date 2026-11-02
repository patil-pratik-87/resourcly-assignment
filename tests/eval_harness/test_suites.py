from resourcly.eval_harness.cases import Case
from resourcly.eval_harness.suites import SUITES

GOLD = {"values": [{"page": 1, "value": 5, "unit": "mm", "kind": "linear", "raw": "5"}]}
PREDICTION = {
    "document": {"values": [{"page": 1, "value": 9, "unit": "mm", "kind": "linear", "raw": "9"}]},
    "issues": [],
}


def test_partial_gold_explains_its_extra_predictions_as_unknown_not_wrong() -> None:
    explain = SUITES["reader"].explain

    full = explain(Case("d", "dev", "full", GOLD), PREDICTION)
    partial = explain(Case("d", "dev", "partial", GOLD), PREDICTION)

    assert "extra predictions (1)" in full
    assert "predictions not in the partial gold (1); they may still be right" in partial


def test_a_gold_with_page_coverage_is_scored_on_its_covered_pages_only() -> None:
    record = {"page": 2, "value": 5, "unit": "mm", "kind": "linear", "raw": "5"}
    gold = {"page_coverage": [2], "values": [record]}
    other_page = {**record, "page": 1, "value": 9, "raw": "9"}
    prediction = {"document": {"values": [record, other_page]}, "issues": []}
    suite = SUITES["reader"]
    case = Case("d", "dev", "full", gold)

    scores = suite.score(case, prediction)

    assert (scores["precision"], scores["recall"]) == (1.0, 1.0)
    assert suite.summarise([(case, prediction)])["precision"] == 1.0
    assert "extra predictions (0)" in suite.explain(case, prediction)


def test_a_bool_page_stays_invalid_under_page_coverage() -> None:
    record = {"page": 2, "value": 5, "unit": "mm", "kind": "linear", "raw": "5"}
    gold = {"page_coverage": [2], "values": [record]}  # True == 1, a page the gold does not cover
    prediction = {"document": {"values": [record, {**record, "page": True}]}, "issues": []}

    scores = SUITES["reader"].score(Case("d", "dev", "full", gold), prediction)

    assert (scores["matched"], scores["predicted"]) == (1, 2)
