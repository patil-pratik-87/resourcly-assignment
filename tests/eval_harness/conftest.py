import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner, Result

from resourcly.eval_harness.cli import app
from resourcly.eval_harness.store import SqliteResultStore
from tests.conftest import CTC01


def title_block(number: int, raw: str) -> dict:
    return {
        "id": f"ctc01-{number:02d}",
        "raw": raw,
        "callout": "title_block",
        "kind": "title_block",
        "tolerance_style": "none",
        "value": None,
        "unit": None,
        "feature_id": None,
        "applies_to": None,
        "datums": [],
        "limits": None,
        "meaning": f"Title block line {raw}.",
        "page": 1,
        "bbox": [0.9, 0.9, 0.95, 0.95],
        "confidence": 1,
        "status": "draft",
    }


@pytest.fixture
def eval_gold(gold_dir: Path, ctc01: dict) -> Path:
    """CTC-01 with two title block values (19 in all) in dev, and partial gold with no PDF in test.

    The text-layer reader finds six title block lines on CTC-01, so two of them match.
    """
    ctc01["values"] += [title_block(18, "Rev D"), title_block(19, "Test Model 1")]
    (gold_dir / "drawings" / f"{CTC01}.json").write_text(json.dumps(ctc01), encoding="utf-8")
    partial = gold_dir / "partial" / "partial_a.json"
    partial.parent.mkdir()
    partial.write_text(json.dumps({**ctc01, "drawing": "partial_a"}), encoding="utf-8")
    (gold_dir / "splits.toml").write_text(
        f'[reader]\ndev = ["{CTC01}"]\ntest = ["partial_a"]\n', encoding="utf-8"
    )
    return gold_dir


@pytest.fixture
def store(tmp_path: Path) -> Iterator[SqliteResultStore]:
    with SqliteResultStore.open(tmp_path / "runs" / "evals.sqlite") as store:
        yield store


@pytest.fixture
def evals(eval_gold: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """`evals` on the eval gold, with its results in a store of the test's own."""
    monkeypatch.setenv("RESOURCLY_TRACE_DB", str(tmp_path / "traces.sqlite"))
    monkeypatch.setenv("RESOURCLY_GOLD_DIR", str(eval_gold))
    monkeypatch.setenv("RESOURCLY_SPLITS", str(eval_gold / "splits.toml"))

    def invoke(*args: str) -> Result:
        return CliRunner().invoke(app, ["--store", str(tmp_path / "evals.sqlite"), *args])

    return invoke
