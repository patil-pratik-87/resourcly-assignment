from dataclasses import replace

from resourcly.eval_harness.compare import compare_runs
from resourcly.eval_harness.models import CaseResult, Run

BASE = Run(
    run_id="base",
    component="reader",
    version="a",
    version_hash="h1",
    split="dev",
    selection={},
    case_set_hash="same",
    started_at="2026-11-01T10:00:00Z",
    git_sha="1",
    git_dirty=False,
    summary={"strict_f1": 0.5, "strict_recall": 0.2, "partial_recall": 0.4},
)


def case(case_id: str, score: float, gold_hash: str = "g") -> CaseResult:
    return CaseResult(
        case_id, "full", gold_hash, f"r:{case_id}", 1.0, None, {}, {"case_score": score}
    )


def test_compare_gives_a_verdict_per_metric_with_the_primary_first() -> None:
    candidate = replace(
        BASE,
        run_id="cand",
        version="b",
        summary={"strict_f1": 0.4, "strict_recall": 0.3, "partial_recall": 0.4},
    )

    result = compare_runs(
        BASE,
        [case("a", 0.5)],
        candidate,
        [case("a", 0.4)],
        metrics=("strict_recall", "strict_f1", "partial_recall"),
        primary="strict_f1",
    )

    assert [(m.name, m.base, m.candidate, m.verdict) for m in result.metrics] == [
        ("strict_f1", 0.5, 0.4, "worse"),
        ("strict_recall", 0.2, 0.3, "better"),
        ("partial_recall", 0.4, 0.4, "no change"),
    ]
    assert result.worse
    assert result.warnings == []


def test_compare_pairs_cases_and_warns_about_unpaired_cases_and_changed_gold() -> None:
    candidate = replace(BASE, run_id="cand", version="b", case_set_hash="other")
    base_cases = [case("a", 0.5), case("b", 0.3), case("c", 0.1)]
    candidate_cases = [case("a", 0.9), case("b", 0.3, gold_hash="new"), case("d", 0.2)]

    result = compare_runs(
        BASE, base_cases, candidate, candidate_cases, metrics=("strict_f1",), primary="strict_f1"
    )

    assert [(c.case_id, c.base, c.candidate) for c in result.cases] == [
        ("a", 0.5, 0.9),
        ("b", 0.3, 0.3),
    ]
    assert [(m.base, m.candidate, m.verdict) for m in result.metrics] == [
        (None, None, "no verdict")
    ]
    assert result.warnings == [
        "no verdict: the runs ran on different cases or gold; rescore the older run first with"
        " `evals run --rescore RUN_ID`",
        "only in base: c",
        "only in candidate: d",
        "gold changed between the runs for b",
    ]
    assert not result.worse
    assert not result.comparable


def test_a_metric_one_run_did_not_measure_gets_no_verdict() -> None:
    candidate = replace(BASE, run_id="cand", summary={**BASE.summary, "partial_recall": None})

    result = compare_runs(BASE, [], candidate, [], metrics=("partial_recall",), primary="strict_f1")

    assert [(m.name, m.base, m.candidate, m.verdict) for m in result.metrics][1] == (
        "partial_recall",
        0.4,
        None,
        "not measured",
    )


def test_runs_that_share_no_case_get_no_verdict() -> None:
    candidate = replace(BASE, run_id="cand", case_set_hash="other")

    result = compare_runs(
        BASE,
        [case("a", 0.5)],
        candidate,
        [case("b", 0.5)],
        metrics=("strict_f1",),
        primary="strict_f1",
    )

    assert result.metrics[0].verdict == "no verdict"
    assert "no verdict: the runs share no case" in result.warnings


def test_any_change_at_all_is_better_or_worse() -> None:
    candidate = replace(BASE, run_id="cand", summary={**BASE.summary, "strict_f1": 0.501})

    result = compare_runs(BASE, [], candidate, [], metrics=(), primary="strict_f1")

    assert result.metrics[0].verdict == "better"


def test_a_lower_is_better_metric_gets_better_when_it_falls() -> None:
    base = replace(BASE, summary={"strict_f1": 0.5, "median_ms": 40.0})
    candidate = replace(base, run_id="cand", summary={"strict_f1": 0.5, "median_ms": 20.0})

    result = compare_runs(
        base,
        [case("a", 1.0)],
        candidate,
        [case("a", 1.0)],
        metrics=("strict_f1", "median_ms"),
        primary="strict_f1",
        lower_is_better=("median_ms",),
    )

    assert [(m.name, m.verdict) for m in result.metrics] == [
        ("strict_f1", "no change"),
        ("median_ms", "better"),
    ]
