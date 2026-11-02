"""The failure suite end to end, with a fake finder that reads the answer from the file name."""

import json
import re
from dataclasses import replace
from pathlib import Path

import pytest
from typer.testing import CliRunner

from resourcly.bootstrap import FINDERS, Implementation, Settings, open_services
from resourcly.eval_harness import harness
from resourcly.eval_harness.cases import check_gold, failure_cases
from resourcly.eval_harness.cli import app
from resourcly.eval_harness.store import SqliteResultStore
from resourcly.models import FigureMatch
from tests.conftest import png


def photo(case_id: str, figure: str, section: str, mode: str, **fields) -> dict:
    """One line of failure/cases.jsonl, in the shape evals/gold/failure/cases.jsonl has."""
    return {
        "case_id": case_id,
        "image": fields.pop("image", f"images/{case_id}.jpg"),
        "kind": "positive",
        "expected_report": figure.split("/")[0],
        "expected_figure": figure,
        "section": section,
        "failure_mode": mode,
        "failure_keywords": [mode],
        "perturbations": ["crop0.80"],
        "unit": figure,
        **fields,
    }


def negative(case_id: str, kind: str = "negative_drawing", **fields) -> dict:
    return {
        "case_id": case_id,
        "image": fields.pop("image", f"images/{case_id}.png"),
        "kind": kind,
        "expected_report": "none",
        "unit": case_id,
        **fields,
    }


ROWS = [
    photo("pos_fig06_v0", "18-061/fig06", "spar_fatigue_N106ER", "fatigue"),
    photo("pos_fig06_v1", "18-061/fig06", "spar_fatigue_N106ER", "fatigue"),
    photo("pos_fig01_v0", "16-006/fig01", "heat_damage", "heat_damage"),
    negative("neg_drawing_ctc01"),
    negative("neg_unrelated_logo", "negative_unrelated", image="../routes/items/other/logo.png"),
    photo("pos_missing", "24-013/fig02", "bending_overstress", "overstress", image="images/no.jpg"),
    negative("neg_drawing_ctc03"),
]
SPLITS = (
    '[failure]\ndev = ["18-061/fig06", "16-006/fig01", "neg_drawing_ctc01",'
    ' "neg_unrelated_logo", "24-013/fig02"]\ntest = ["neg_drawing_ctc03"]\n'
)
FIG06 = FigureMatch(
    figure="18-061/fig06", report="18-061", section="spar_fatigue_N106ER", failure_mode="fatigue"
)


def write_failures(gold_dir: Path, rows: list[dict], splits: str) -> None:
    (gold_dir / "failure").mkdir(exist_ok=True)
    (gold_dir / "failure" / "cases.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
    )
    (gold_dir / "splits.toml").write_text(splits, encoding="utf-8")


class NameFinder:
    """Finds figure 6 of report 18-061 in any photo whose file name says pos_fig06."""

    def find(self, photo) -> list[FigureMatch]:
        return [FIG06] if "pos_fig06" in photo.name or "logo" in photo.name else []


@pytest.fixture
def failing(gold_dir: Path, settings: Settings, tmp_path: Path, monkeypatch) -> Settings:
    write_failures(gold_dir, ROWS, SPLITS)
    for r in ROWS:
        if r["image"] != "images/no.jpg":
            path = gold_dir / "failure" / r["image"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(png())
    monkeypatch.setitem(FINDERS, "fake", Implementation(lambda settings, params: NameFinder()))
    versions = tmp_path / "versions" / "failure"
    versions.mkdir(parents=True)
    (versions / "fake-v1.toml").write_text('impl = "fake"\n', encoding="utf-8")
    return replace(settings, versions_dir=versions.parent)


def test_a_split_takes_every_case_of_the_units_it_names(failing: Settings) -> None:
    with open_services(failing) as services:
        dev = failure_cases(services, "dev")
        test = failure_cases(services, "test")

    assert [(c.case_id, c.split, c.stratum) for c in dev] == [
        ("neg_drawing_ctc01", "dev", "negative_drawing"),
        ("neg_unrelated_logo", "dev", "negative_unrelated"),
        ("pos_fig01_v0", "dev", "positive"),
        ("pos_fig06_v0", "dev", "positive"),
        ("pos_fig06_v1", "dev", "positive"),
        ("pos_missing", "dev", "positive"),
    ]
    assert [c.case_id for c in test] == ["neg_drawing_ctc03"]


def test_a_failure_run_stores_each_answer_and_scores_the_split(
    failing: Settings, store: SqliteResultStore
) -> None:
    run = harness.run("failure", "fake-v1", settings=failing, store=store, split="dev")
    cases = {case.case_id: case for case in store.cases(run.run_id)}

    assert cases["pos_fig06_v0"].prediction["figures"][0]["figure"] == "18-061/fig06"
    assert cases["pos_fig06_v0"].scores == {
        "case_score": 1.0,
        "section@1": 1.0,
        "mode@3": 1.0,
        "top": "18-061/fig06",
    }
    assert cases["pos_fig01_v0"].scores["case_score"] == 0.0
    assert cases["neg_drawing_ctc01"].scores == {"case_score": 1.0, "kept_out": 1.0, "top": None}
    assert cases["neg_unrelated_logo"].scores["kept_out"] == 0.0
    assert cases["pos_missing"].error.startswith("NotFound: failure/images/no.jpg is not in ")
    assert (run.n_cases, run.errors) == (6, 1)
    assert run.summary["section@1"] == pytest.approx(2 / 4)
    assert run.summary["kept_out"] == pytest.approx(1 / 2)


def test_every_answer_can_be_looked_up(failing: Settings, store: SqliteResultStore) -> None:
    run = harness.run(
        "failure", "fake-v1", settings=failing, store=store, case_ids=("pos_fig06_v1",)
    )

    with open_services(failing) as services:
        [event] = services.traces.lookup(f"{run.run_id}:pos_fig06_v1").events

    assert (event.step, event.output["top"]) == ("failure.find", "18-061/fig06")


def test_evals_run_failure_prints_the_summary(
    failing: Settings, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("RESOURCLY_VERSIONS_DIR", str(failing.versions_dir))
    monkeypatch.setenv("RESOURCLY_TRACE_DB", str(failing.trace_path))
    monkeypatch.setenv("RESOURCLY_GOLD_DIR", str(failing.gold_dir))
    monkeypatch.setenv("RESOURCLY_SPLITS", str(failing.splits_path))
    store = tmp_path / "e.sqlite"

    result = CliRunner().invoke(
        app, ["--store", str(store), "run", "failure", "--version", "fake-v1"]
    )
    shown = CliRunner().invoke(app, ["--store", str(store), "list", "runs", "failure"])

    assert result.exit_code == 0, result.output
    assert re.search(r"section@1 \(primary\) +0\.500", result.output)
    assert re.search(r"kept_out +0\.500", result.output)
    assert "section@1 0.500" in shown.output


def test_the_gold_check_accepts_the_cases_and_warns_about_a_missing_image(
    failing: Settings,
) -> None:
    with open_services(failing) as services:
        found = check_gold(services)

    failure = [(level, message) for level, message in found if message.startswith("failure")]
    assert ("ok", "failure 7 case(s): 4 photo(s), 3 negative(s)") in failure
    assert (
        "warning",
        "failure 1 of 7 image(s) are missing; they are committed, so restore them from git",
    ) in failure
    assert [level for level, _ in failure if level == "error"] == []


def test_the_gold_check_refuses_broken_rows(gold_dir: Path, settings: Settings) -> None:
    rows = [
        *ROWS,
        negative("neg_drawing_ctc01"),
        negative("neg_drawing_ctc05"),
        negative("neg_odd", "negative_logo"),
        {**photo("pos_bare", "18-061/fig06", "s", "m"), "section": None},
        {"case_id": "x_bare", "kind": "positive"},
    ]
    write_failures(gold_dir, rows, SPLITS + 'train = ["18-061/fig06"]\n')

    with open_services(settings) as services:
        found = check_gold(services)

    errors = [message for level, message in found if level == "error"]
    warnings = [message for level, message in found if level == "warning"]
    assert "failure case id neg_drawing_ctc01 is used more than once" in errors
    assert (
        "failure neg_odd has kind 'negative_logo';"
        " use positive, negative_drawing or negative_unrelated"
    ) in errors
    assert "failure pos_bare lacks section" in errors
    assert "failure cases.jsonl line 12 lacks image, unit" in errors
    assert "failure 18-061/fig06 is in more than one split: dev, train" in errors
    assert "failure neg_drawing_ctc05 has gold but is in no split" in warnings
