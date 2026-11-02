from pathlib import Path

import pytest

from resourcly.bootstrap import Settings, open_services
from resourcly.eval_harness import harness
from resourcly.eval_harness.store import SqliteResultStore
from tests.conftest import CTC01


def test_a_run_reads_each_selected_drawing_scores_it_and_stores_it(
    eval_gold: Path, settings: Settings, store: SqliteResultStore
) -> None:
    run = harness.run("reader", "textlayer-v0", settings=settings, store=store, split="dev")

    assert (run.component, run.version, run.split, run.n_cases, run.errors) == (
        "reader",
        "textlayer-v0",
        "dev",
        1,
        0,
    )
    assert run.summary["precision"] == 2 / 6
    assert run.summary["recall"] == 2 / 19
    [case] = store.cases(run.run_id)
    assert (case.case_id, case.stratum, case.request_id) == (CTC01, "full", f"{run.run_id}:{CTC01}")
    assert len(case.prediction["document"]["values"]) == 6
    assert case.scores["matched"] == 2
    assert case.scores["case_score"] == case.scores["f1"] == pytest.approx(4 / 25)
    assert store.run(run.run_id) == run


def test_a_failed_call_is_stored_with_its_error_and_scored_as_a_miss(
    eval_gold: Path, settings: Settings, store: SqliteResultStore
) -> None:
    run = harness.run("reader", "textlayer-v0", settings=settings, store=store, split="test")

    [case] = store.cases(run.run_id)
    assert run.errors == 1
    assert case.error == "NotFound: no drawing named partial_a"
    assert case.prediction is None
    assert (case.scores["matched"], case.scores["gold"]) == (0, 19)
    assert case.scores["case_score"] == case.scores["recall"] == 0.0
    assert run.summary["partial_recall"] == 0.0


def test_a_run_takes_every_case_of_the_split_or_only_the_named_ones(
    eval_gold: Path, settings: Settings, store: SqliteResultStore
) -> None:
    every = {"settings": settings, "store": store, "split": "all"}
    whole = harness.run("reader", "textlayer-v0", **every)
    named = harness.run("reader", "textlayer-v0", case_ids=("partial_a",), **every)

    assert [c.case_id for c in store.cases(whole.run_id)] == [CTC01, "partial_a"]
    assert [c.case_id for c in store.cases(named.run_id)] == ["partial_a"]
    assert (whole.case_ids, named.case_ids) == ([], ["partial_a"])


def test_a_limit_takes_the_first_cases_of_the_split(
    eval_gold: Path, settings: Settings, store: SqliteResultStore
) -> None:
    every = {"settings": settings, "store": store, "split": "all"}
    first = harness.run("reader", "textlayer-v0", limit=1, **every)
    beyond = harness.run("reader", "textlayer-v0", limit=5, **every)

    assert [c.case_id for c in store.cases(first.run_id)] == [CTC01]
    assert first.case_ids == [CTC01]
    assert [c.case_id for c in store.cases(beyond.run_id)] == [CTC01, "partial_a"]
    assert beyond.case_ids == []


def test_a_component_without_a_version_cannot_run(
    settings: Settings, store: SqliteResultStore
) -> None:
    with pytest.raises(LookupError, match="no reader version 'v1'"):
        harness.run("reader", "v1", settings=settings, store=store)
    assert store.runs() == []


def test_a_run_with_no_cases_is_refused_and_not_stored(
    eval_gold: Path, settings: Settings, store: SqliteResultStore
) -> None:
    with pytest.raises(ValueError, match="no reader case of the dev split was selected"):
        harness.run("reader", "textlayer-v0", settings=settings, store=store, case_ids=("nope",))
    assert store.runs() == []


def test_every_case_leaves_a_trace_under_its_request_id(
    eval_gold: Path, settings: Settings, store: SqliteResultStore
) -> None:
    run = harness.run("reader", "textlayer-v0", settings=settings, store=store, split="all")

    with open_services(settings) as services:
        traces = [services.traces.lookup(case.request_id) for case in store.cases(run.run_id)]

    assert [[e.input["drawing"] for e in trace.events] for trace in traces] == [
        [CTC01],
        ["partial_a"],
    ]
    assert traces[1].events[0].error == "NotFound: no drawing named partial_a"
