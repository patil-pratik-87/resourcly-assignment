import json
from pathlib import Path

from check_photo_answers import check
from resourcly.bootstrap import PROJECT_ROOT, Settings, open_services

GOLD = PROJECT_ROOT / "evals" / "gold"


def test_each_case_is_answered_and_stored_with_what_the_model_said(
    settings: Settings, tmp_path: Path
) -> None:
    cases = tmp_path / "cases.jsonl"
    rows = [
        {
            "case_id": "spar",
            "image": "failure/images/pos_18-061_fig05_v1.jpg",
            "kind": "report_photo",
            "expected": "18-061/fig05",
        },
        {
            "case_id": "vcr",
            "image": "routes/items/photo/commons_ourbrokenvcrpart3detail7.jpg",
            "kind": "other_part",
            "expected": "not in the reports",
        },
    ]
    cases.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    model_free = settings.with_version("failure", "shuffled-v0").with_version(
        "answer", "captions-v0"
    )

    with open_services(model_free) as services:
        found = check(services, cases, GOLD)

    assert [row["case_id"] for row in found] == ["spar", "vcr"]
    spar = found[0]
    assert (spar["kind"], spar["expected"]) == ("report_photo", "18-061/fig05")
    assert (spar["failure"], spar["answer_version"]) == (
        "shuffled-v0 (shuffled)",
        "captions-v0 (captions)",
    )
    assert spar["answer"]["matched"] is True
    assert spar["answer"]["figures"][0]["figure"]
    assert spar["model_text"].startswith("The closest report figure is")
    assert spar["seconds"] >= 0
