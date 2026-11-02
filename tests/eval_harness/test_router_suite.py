"""The router suite end to end, with a fake router that reads the answer from the file name."""

import re
from dataclasses import replace
from pathlib import Path

import pytest
from typer.testing import CliRunner

from resourcly.bootstrap import ROUTERS, Implementation, Settings, open_services
from resourcly.eval_harness import harness
from resourcly.eval_harness.cli import app
from resourcly.eval_harness.store import SqliteResultStore
from resourcly.models import LayerVerdict, Route
from tests.eval_harness.test_route_gold import row, write_routes

ROWS = [
    row("d_a", "drawing", "ctc01"),
    row("d_b", "drawing", "ctc01", file="items/photo/d_b.png"),  # filed as a photo: one mistake
    row("p_a", "photo", "ntsb_18-061"),
    row("o_logo", "other", "ntsb_18-061"),
    row("t_01", "text", "text_01", kind="text", file=None, text="What failed?"),
    row("d_missing", "drawing", "ctc01", file="items/drawing/absent.png"),
    row("d_train", "drawing", "ctc03"),
]
SPLITS = '[router]\ntrain = ["ctc03"]\ndev = ["ctc01", "ntsb_18-061", "text_01"]\ntest = []\n'


class NameLayer:
    """Routes an attachment by the folder its file name is in."""

    name = "probe"
    called = "fake probe reading the file name"

    def decide(self, attachment) -> LayerVerdict:
        if attachment is None:
            return LayerVerdict(Route.TEXT, "no attachment", 1.0)
        for route in (Route.DRAWING, Route.PHOTO):
            if f"/{route.value}/" in attachment.name:
                return LayerVerdict(route, f"filed under {route.value}", 0.99)
        return LayerVerdict(Route.OTHER, "filed elsewhere", 0.6)


@pytest.fixture
def routed(gold_dir: Path, settings: Settings, tmp_path: Path, monkeypatch) -> Settings:
    write_routes(gold_dir, ROWS, SPLITS)
    for r in ROWS:
        if r["file"] and "absent" not in r["file"]:
            path = gold_dir / "routes" / r["file"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"\x89PNG\r\n\x1a\n")
    monkeypatch.setitem(ROUTERS, "fake", Implementation(lambda settings, params: [NameLayer()]))
    versions = tmp_path / "versions" / "router"
    versions.mkdir(parents=True)
    (versions / "fake-v1.toml").write_text('impl = "fake"\n', encoding="utf-8")
    return replace(settings, versions_dir=versions.parent)


def test_a_router_run_stores_each_routing_and_scores_the_split(
    routed: Settings, store: SqliteResultStore
) -> None:
    run = harness.run("router", "fake-v1", settings=routed, store=store, split="dev")
    cases = {case.case_id: case for case in store.cases(run.run_id)}

    assert sorted(cases) == ["d_a", "d_b", "d_missing", "o_logo", "p_a", "t_01"]
    assert cases["d_a"].prediction["route"] == "drawing"
    assert cases["d_a"].prediction["layer"] == "probe"
    assert cases["d_a"].prediction["request_id"] == cases["d_a"].request_id
    assert cases["d_a"].scores == {
        "case_score": 1.0,
        "correct": 1.0,
        "route": "drawing",
        "layer": "probe",
        "confidence": 0.99,
    }
    assert cases["d_b"].scores["case_score"] == 0.0
    assert cases["d_missing"].error.startswith(
        "NotFound: routes/items/drawing/absent.png is not in "
    )
    summary = run.summary
    assert (run.n_cases, run.errors) == (6, 1)
    assert summary == {
        "accuracy": pytest.approx(4 / 6),
        "drawing_recall": 1 / 3,
        "other_kept_out": 1.0,
    }


def test_every_routed_case_can_be_looked_up(routed: Settings, store: SqliteResultStore) -> None:
    run = harness.run("router", "fake-v1", settings=routed, store=store, case_ids=("p_a",))

    with open_services(routed) as services:
        [event] = services.traces.lookup(f"{run.run_id}:p_a").events

    assert (event.step, event.output["route"]) == ("route.probe", "photo")


def test_evals_run_router_prints_the_summary(routed: Settings, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("RESOURCLY_VERSIONS_DIR", str(routed.versions_dir))
    monkeypatch.setenv("RESOURCLY_TRACE_DB", str(routed.trace_path))
    monkeypatch.setenv("RESOURCLY_GOLD_DIR", str(routed.gold_dir))
    monkeypatch.setenv("RESOURCLY_SPLITS", str(routed.splits_path))
    result = CliRunner().invoke(
        app,
        [
            "--store",
            str(tmp_path / "e.sqlite"),
            "run",
            "router",
            "--version",
            "fake-v1",
        ],
    )

    assert result.exit_code == 0, result.output
    assert re.search(r"accuracy \(primary\) +0\.667", result.output)
    assert re.search(r"other_kept_out +1\.000", result.output)
