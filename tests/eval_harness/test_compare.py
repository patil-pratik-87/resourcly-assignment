from dataclasses import replace

import pytest

from resourcly.eval_harness.cases import Case
from resourcly.eval_harness.compare import compare_runs
from resourcly.eval_harness.models import CaseResult, Run
from resourcly.eval_harness.suites import SUITES

READER = SUITES["reader"]
BASE = Run(
    run_id="base",
    component="reader",
    version="a",
    version_hash="h1",
    split="dev",
    case_ids=[],
    case_set_hash="same",
    started_at="2026-11-01T10:00:00Z",
    git_sha="1",
    git_dirty=False,
)
CANDIDATE = replace(BASE, run_id="cand", version="b")


def value(number: float) -> dict:
    return {"page": 1, "value": number, "unit": "mm", "kind": "linear", "raw": str(number)}


GOLD = {
    "a": Case("a", "dev", "full", {"values": [value(1), value(2)]}),
    "b": Case("b", "dev", "partial", {"values": [value(3), value(4)]}),
}


def answer(case_id: str, *numbers: float) -> CaseResult:
    """A stored reading of the case with these values; its stored scores are stale on purpose."""
    reading = {"document": {"values": [value(n) for n in numbers]}, "issues": []}
    return CaseResult(case_id, "full", "old", f"r:{case_id}", 1.0, None, reading, {})


def test_both_runs_are_scored_again_on_the_current_gold_with_the_primary_first() -> None:
    result = compare_runs(
        READER,
        GOLD,
        BASE,
        [answer("a", 1, 2), answer("b", 3)],
        CANDIDATE,
        [answer("a", 1, 9), answer("b", 3, 4)],
    )

    assert [(m.name, m.base, m.candidate, m.verdict) for m in result.metrics] == [
        ("f1", 1.0, 0.5, "worse"),
        ("precision", 1.0, 0.5, "worse"),
        ("recall", 1.0, 0.5, "worse"),
        ("partial_recall", 0.5, 1.0, "better"),
    ]
    assert [(c.case_id, c.base, c.candidate) for c in result.cases] == [
        ("a", 1.0, 0.5),
        ("b", 0.5, 1.0),
    ]
    assert result.worse
    assert result.warnings == []


def test_cases_one_run_lacks_or_with_no_gold_now_are_left_out_with_a_warning() -> None:
    result = compare_runs(
        READER,
        GOLD,
        BASE,
        [answer("a", 1, 2), answer("b", 3), answer("gone", 5)],
        CANDIDATE,
        [answer("a", 1, 2), answer("gone", 5), answer("new", 6)],
    )

    assert [c.case_id for c in result.cases] == ["a"]
    assert result.metrics[0].verdict == "no change"
    assert result.metrics[3].verdict == "not measured"
    assert result.warnings == ["only in base: b", "only in candidate: new", "no gold now for gone"]


def test_a_failed_call_is_scored_as_an_empty_answer() -> None:
    failed = replace(answer("a"), prediction=None, error="RuntimeError: no GPU")

    result = compare_runs(READER, GOLD, BASE, [answer("a", 1, 2)], CANDIDATE, [failed])

    assert result.metrics[0].candidate == 0.0


def test_runs_that_share_no_case_with_gold_are_refused() -> None:
    with pytest.raises(ValueError, match="the runs share no case that has gold now"):
        compare_runs(READER, GOLD, BASE, [answer("a", 1)], CANDIDATE, [answer("b", 3)])


def test_runs_of_two_components_are_refused() -> None:
    router = replace(CANDIDATE, component="router")

    with pytest.raises(ValueError, match="cannot compare a reader run with a router run"):
        compare_runs(READER, GOLD, BASE, [], router, [])
