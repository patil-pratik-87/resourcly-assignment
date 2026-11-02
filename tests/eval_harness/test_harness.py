import json
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
    assert run.summary["strict_precision"] == 2 / 6
    assert run.summary["strict_recall"] == 2 / 19
    [case] = store.cases(run.run_id)
    assert (case.case_id, case.stratum, case.request_id) == (CTC01, "full", f"{run.run_id}:{CTC01}")
    assert len(case.prediction["document"]["values"]) == 6
    assert case.scores["strict_matched"] == 2
    assert case.scores["case_score"] == case.scores["strict_f1"] == pytest.approx(4 / 25)
    assert store.run(run.run_id) == run


def test_a_failed_call_is_stored_with_its_error_and_scored_as_a_miss(
    eval_gold: Path, settings: Settings, store: SqliteResultStore
) -> None:
    run = harness.run("reader", "textlayer-v0", settings=settings, store=store, split="test")

    [case] = store.cases(run.run_id)
    assert run.errors == 1
    assert case.error == "NotFound: no drawing named partial_a"
    assert case.prediction is None
    assert (case.scores["strict_matched"], case.scores["gold"]) == (0, 19)
    assert case.scores["case_score"] == case.scores["strict_recall"] == 0.0
    assert run.summary["partial_recall"] == 0.0


def test_a_run_takes_every_case_of_the_split_or_only_the_named_ones(
    eval_gold: Path, settings: Settings, store: SqliteResultStore
) -> None:
    every = {"settings": settings, "store": store, "split": "all"}
    whole = harness.run("reader", "textlayer-v0", **every)
    named = harness.run("reader", "textlayer-v0", case_ids=("partial_a",), **every)

    assert [c.case_id for c in store.cases(whole.run_id)] == [CTC01, "partial_a"]
    assert [c.case_id for c in store.cases(named.run_id)] == ["partial_a"]
    assert named.selection == {"case_ids": ["partial_a"]}


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


def test_rescore_scores_the_stored_predictions_against_the_current_gold(
    eval_gold: Path, settings: Settings, store: SqliteResultStore
) -> None:
    first = harness.run("reader", "textlayer-v0", settings=settings, store=store, split="dev")
    path = eval_gold / "drawings" / f"{CTC01}.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["values"] = [v for v in document["values"] if v["raw"] != "Rev D"]
    path.write_text(json.dumps(document), encoding="utf-8")

    again = harness.rescore(first.run_id, settings=settings, store=store)

    [before], [after] = store.cases(first.run_id), store.cases(again.run_id)
    assert (again.rescored_from, again.version, again.split) == (
        first.run_id,
        "textlayer-v0",
        "dev",
    )
    assert after.prediction == before.prediction
    assert after.request_id == before.request_id
    assert (after.scores["strict_matched"], after.scores["gold"]) == (1, 18)
    assert after.gold_hash != before.gold_hash
    assert store.run(first.run_id) == first


def test_rescore_stores_the_stratum_the_case_has_now(
    eval_gold: Path, settings: Settings, store: SqliteResultStore
) -> None:
    first = harness.run("reader", "textlayer-v0", settings=settings, store=store, split="dev")
    name = f"{CTC01}.json"
    (eval_gold / "drawings" / name).rename(eval_gold / "partial" / name)

    again = harness.rescore(first.run_id, settings=settings, store=store)

    [case] = store.cases(again.run_id)
    assert case.stratum == "partial"
    assert case.scores["case_score"] == case.scores["strict_recall"]


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
