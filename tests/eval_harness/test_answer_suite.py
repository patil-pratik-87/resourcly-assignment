"""The answer suite end to end: the fake finder of the failure suite and the captions answerer."""

from dataclasses import replace
from pathlib import Path

import pytest

from resourcly.bootstrap import FINDERS, PROJECT_ROOT, Implementation, Settings, open_services
from resourcly.eval_harness import harness
from resourcly.eval_harness.store import SqliteResultStore
from resourcly.eval_harness.suites import SUITES
from tests.conftest import png
from tests.eval_harness.test_failure_suite import ROWS, SPLITS, NameFinder, write_failures

INDEX = PROJECT_ROOT / "versions" / "failure" / "indexes" / "dinov2-base-v1.json"


@pytest.fixture
def answering(gold_dir: Path, settings: Settings, tmp_path: Path, monkeypatch) -> Settings:
    write_failures(gold_dir, ROWS, SPLITS)
    for r in ROWS:
        if r["image"] != "images/no.jpg":
            path = gold_dir / "failure" / r["image"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(png())
    monkeypatch.setattr(NameFinder, "hidden", [])
    monkeypatch.setitem(FINDERS, "fake", Implementation(lambda settings, params: NameFinder()))
    versions = tmp_path / "versions"
    (versions / "failure").mkdir(parents=True)
    (versions / "failure" / "fake-v1.toml").write_text('impl = "fake"\n', encoding="utf-8")
    (versions / "answer").mkdir()
    (versions / "answer" / "captions-v0.toml").write_text(
        f'impl = "captions"\nindex = "{INDEX}"\n', encoding="utf-8"
    )
    return replace(settings, versions_dir=versions).with_version("failure", "fake-v1")


def test_an_answer_run_answers_each_photo_held_out_and_scores_it(
    answering: Settings, store: SqliteResultStore
) -> None:
    run = harness.run("answer", "captions-v0", settings=answering, store=store, split="dev")
    cases = {case.case_id: case for case in store.cases(run.run_id)}

    fig06 = cases["pos_fig06_v0"]
    assert [f["citation"]["source"] for f in fig06.prediction["findings"]] == ["18-061 fig05"]
    assert fig06.scores == {
        "case_score": 1.0,
        "correct": 1.0,
        "matched": True,
        "report_cited": 1.0,
        "mode_named": 1.0,
        "citations": 1,
        "valid_citations": 1,
    }
    assert cases["pos_fig01_v0"].prediction["not_in_reports"] is True
    assert cases["pos_fig01_v0"].scores["correct"] == 0.0
    assert cases["neg_drawing_ctc01"].scores["kept_out"] == 1.0
    assert cases["neg_unrelated_logo"].scores["kept_out"] == 0.0
    assert NameFinder.hidden == [set(), set(), {"16-006/fig01"}, {"18-061/fig06"}, {"18-061/fig06"}]
    assert (run.component, run.n_cases, run.errors) == ("answer", 6, 1)
    assert run.summary["correct"] == pytest.approx(3 / 6)
    assert run.summary["kept_out"] == 0.5


def test_each_answer_is_traced_from_the_finder_to_the_answer(
    answering: Settings, store: SqliteResultStore
) -> None:
    run = harness.run(
        "answer", "captions-v0", settings=answering, store=store, case_ids=("pos_fig06_v1",)
    )

    with open_services(answering) as services:
        events = services.traces.lookup(f"{run.run_id}:pos_fig06_v1").events

    assert [event.step for event in events] == ["failure.find", "answer.photo"]


def test_explain_shows_the_answer_its_sources_and_what_was_expected(
    answering: Settings, store: SqliteResultStore
) -> None:
    run = harness.run(
        "answer", "captions-v0", settings=answering, store=store, case_ids=("pos_fig06_v0",)
    )
    [result] = store.cases(run.run_id)
    with open_services(answering) as services:
        [case] = [c for c in SUITES["answer"].load(services, "dev") if c.case_id == "pos_fig06_v0"]

    lines = SUITES["answer"].explain(case, result.prediction)

    assert lines[0] == "expected report 18-061, failure mode fatigue (keywords: fatigue)"
    assert lines[1].startswith("matched: The closest report figure is 18-061 fig05")
    assert "  [18-061 fig05] valid  Figure 5. Closer views" in "\n".join(lines)
    assert lines[-1] == "closest figures: 18-061/fig05"
