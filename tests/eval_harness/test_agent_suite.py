"""The agent suite end to end: whole conversations sent to the agent with model-free versions."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from resourcly.bootstrap import PROJECT_ROOT, Settings
from resourcly.eval_harness import harness
from resourcly.eval_harness.store import SqliteResultStore
from tests.conftest import CTC01

PDF = "routes/items/drawing/ctc01.pdf"
ROWS = [
    {
        "case_id": "a-text",
        "kind": "text",
        "unit": "a-text",
        "turns": [
            {"text": "What throttle position was measured on the accident control?", "files": []}
        ],
        "items": [
            {"item": "message", "route": "text", "answer": {"kind": "text", "pages": ["16-006 p2"]}}
        ],
    },
    {
        "case_id": "a-read",
        "kind": "drawing",
        "unit": "a-drawing",
        "turns": [{"text": "read this", "files": [PDF]}],
        "items": [{"item": "ctc01", "route": "drawing", "reader_gold": CTC01, "answer": None}],
    },
    {
        "case_id": "a-follow",
        "kind": "follow-up",
        "unit": "a-follow",
        "turns": [
            {"text": "read this", "files": [PDF]},
            {"text": "What material is it made of?", "files": [], "about": ["@0/ctc01"]},
        ],
        "items": [
            {"item": "message", "route": "text", "answer": {"kind": "none", "route": "drawing"}}
        ],
    },
    {
        "case_id": "a-wrong-card",
        "kind": "drawing",
        "unit": "a-drawing",
        "turns": [{"text": "What angle is dimensioned?", "files": [PDF]}],
        "items": [{"item": "ctc01", "route": "drawing", "answer": None}],
        "notes": "the gold expects no answer, so the one the agent gives is on a wrong card",
    },
]


@pytest.fixture
def conversing(gold_dir: Path, settings: Settings, tmp_path: Path) -> Settings:
    (gold_dir / "agent").mkdir()
    (gold_dir / "agent" / "messages.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in ROWS), encoding="utf-8"
    )
    pdf = gold_dir / PDF
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes((PROJECT_ROOT / "data" / "drawings" / f"{CTC01}.pdf").read_bytes())
    (gold_dir / "splits.toml").write_text(
        '[agent]\ndev = ["a-text", "a-drawing", "a-follow"]\n', encoding="utf-8"
    )
    return replace(settings, eval_uploads_dir=tmp_path / "agent-uploads")


def test_each_conversation_is_sent_whole_and_its_last_turn_scored(
    conversing: Settings, store: SqliteResultStore
) -> None:
    run = harness.run("agent", "rules-v0", settings=conversing, store=store)
    cases = {case.case_id: case for case in store.cases(run.run_id)}

    assert (run.component, run.version, run.errors) == ("agent", "rules-v0", 0)
    assert cases["a-text"].scores["case_score"] == 1.0
    read = cases["a-read"].scores
    assert (read["case_score"], read["gold"], read["predicted"]) == (1.0, 17, 6)
    follow = cases["a-follow"]
    assert len(follow.prediction["requests"]) == 2
    assert follow.prediction["requests"][1]["about"] == [
        f"{follow.prediction['requests'][0]['request_id']}/ctc01"
    ]
    assert follow.scores["case_score"] == 1.0
    assert cases["a-wrong-card"].scores["cards"] == 0.0
    assert run.summary["fully_right"] == pytest.approx(3 / 4)
    assert run.summary["follow-up"] == 1.0
    # the agent's requests stay out of the chat's request store
    assert not conversing.uploads_dir.exists()
    assert (conversing.eval_uploads_dir / follow.prediction["requests"][0]["request_id"]).is_dir()
