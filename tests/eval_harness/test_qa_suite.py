"""The qa suite end to end with the model-free rules-v0, on drawing, text, photo and none cases."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from resourcly.bootstrap import FINDERS, PROJECT_ROOT, Implementation, Settings
from resourcly.eval_harness import harness, metrics
from resourcly.eval_harness.store import SqliteResultStore
from tests.conftest import CTC01, png
from tests.eval_harness.test_failure_suite import NameFinder

INDEX = PROJECT_ROOT / "versions" / "failure" / "indexes" / "dinov2-base-v1.json"
ROWS = [
    {
        "case_id": "ctc01-angle",
        "kind": "drawing",
        "unit": "ctc01",
        "drawing": CTC01,
        "question": "What angle is dimensioned on this part?",
        "expected": [{"value": 60, "unit": "deg"}],
    },
    {
        "case_id": "ctc01-hole",
        "kind": "place",
        "unit": "ctc01",
        "drawing": CTC01,
        "question": "What is the diameter of the hole in the right lobe?",
        "expected": [{"value": [34.8, 35.2], "unit": "mm"}],
    },
    {
        "case_id": "n-ctc01-runout",
        "kind": "none",
        "route": "drawing",
        "unit": "ctc01",
        "drawing": CTC01,
        "question": "What is the circular runout tolerance?",
    },
    {
        "case_id": "t-throttle",
        "kind": "text",
        "unit": "text-16-006",
        "question": "What throttle position was measured on the accident control?",
        "pages": ["16-006 p2"],
    },
    {
        "case_id": "p-fig06",
        "kind": "photo",
        "unit": "18-061/fig06",
        "question": "Where did this crack start?",
        "image": "images/pos_fig06_v0.png",
        "expected_report": "18-061",
        "expected_figure": "18-061/fig06",
        "section": "spar_fatigue_N106ER",
        "failure_mode": "fatigue",
    },
    {"case_id": "broken", "kind": "text", "unit": "text-16-006", "question": "No pages?"},
]


@pytest.fixture
def qa(gold_dir: Path, settings: Settings, tmp_path: Path, monkeypatch) -> Settings:
    answers = gold_dir / "answers"
    answers.mkdir()
    (answers / "questions.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in ROWS), encoding="utf-8"
    )
    (gold_dir / "failure" / "images").mkdir(parents=True)
    (gold_dir / "failure" / "images" / "pos_fig06_v0.png").write_bytes(png())
    (gold_dir / "splits.toml").write_text(
        '[qa]\ndev = ["ctc01", "text-16-006", "18-061/fig06"]\n', encoding="utf-8"
    )
    monkeypatch.setattr(NameFinder, "hidden", [])
    monkeypatch.setitem(FINDERS, "fake", Implementation(lambda settings, params: NameFinder()))
    versions = tmp_path / "versions"
    for component in ("failure", "answer", "qa"):
        (versions / component).mkdir(parents=True)
    (versions / "failure" / "fake-v1.toml").write_text('impl = "fake"\n', encoding="utf-8")
    (versions / "answer" / "captions-v0.toml").write_text(
        f'impl = "captions"\nindex = "{INDEX}"\n', encoding="utf-8"
    )
    rules = (PROJECT_ROOT / "versions" / "qa" / "rules-v0.toml").read_text(encoding="utf-8")
    (versions / "qa" / "rules-v0.toml").write_text(rules, encoding="utf-8")
    (versions / "qa" / "rules-gold.toml").write_text(
        rules.replace('evidence = "reader"', 'evidence = "gold"'), encoding="utf-8"
    )
    return replace(settings, versions_dir=versions).with_version("failure", "fake-v1")


def test_a_qa_run_answers_each_case_by_its_route_and_scores_it(
    qa: Settings, store: SqliteResultStore, caplog: pytest.LogCaptureFixture
) -> None:
    run = harness.run("qa", "rules-v0", settings=qa, store=store, split="dev")
    cases = {case.case_id: case for case in store.cases(run.run_id)}

    assert "broken lacks pages; skipped" in caplog.text
    assert sorted(cases) == ["ctc01-angle", "ctc01-hole", "n-ctc01-runout", "p-fig06", "t-throttle"]
    assert cases["ctc01-angle"].prediction["outcome"] == "answer"
    assert cases["ctc01-angle"].prediction["shown_values"][0]["raw"] == "60° ±0.5°"
    assert cases["ctc01-angle"].scores["case_score"] == metrics.RIGHT
    assert cases["ctc01-hole"].scores["case_score"] == metrics.AMONG_CANDIDATES
    assert cases["n-ctc01-runout"].prediction["outcome"] == "none"
    assert cases["n-ctc01-runout"].scores["case_score"] == metrics.RIGHT
    assert cases["t-throttle"].prediction["citations"][0]["ref"] == "16-006 p2"
    assert cases["t-throttle"].scores["case_score"] == metrics.RIGHT
    assert NameFinder.hidden == [{"18-061/fig06"}]
    assert run.summary["answer_score"] == pytest.approx((1 + 0.5 + 1 + 1 + 1) / 5)
    assert run.summary["place"] == 0.5
    assert run.summary["wrong_shown"] == 0


def test_the_gold_evidence_answers_from_the_hand_checked_values(
    qa: Settings, store: SqliteResultStore
) -> None:
    run = harness.run("qa", "rules-gold", settings=qa, store=store, case_ids=("ctc01-angle",))

    [case] = store.cases(run.run_id)
    assert case.prediction["citations"][0]["ref"] == "ctc01-13"
    assert case.prediction["shown_values"][0]["raw"] == "60° ±0.5°"
