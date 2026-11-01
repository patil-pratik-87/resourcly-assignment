import json
from pathlib import Path

import pytest

from resourcly.bootstrap import Settings, open_services
from resourcly.evals.cases import check_gold, route_cases


def row(item_id: str, label: str, unit: str, **fields) -> dict:
    """One line of routes.jsonl, in the shape evals/gold/routes/routes.jsonl has."""
    return {
        "id": item_id,
        "label": label,
        "kind": fields.pop("kind", "image"),
        "file": fields.pop("file", f"items/{label}/{item_id}.png"),
        "group": unit,
        "source": "test",
        "variant": "test",
        "notes": "",
        "text": None,
        "attachment": None,
        "unit": unit,
        **fields,
    }


ROWS = [
    row("d_ctc01_pdf", "drawing", "ctc01", kind="pdf", file="items/drawing/ctc01.pdf"),
    row("d_ctc01_p1_r72", "drawing", "ctc01"),
    row("p_16006_x32", "photo", "ntsb_16-006"),
    row("t_01", "text", "text_01", kind="text", file=None, text="What failed?"),
    row(
        "tp_01",
        "drawing",
        "ctc01",
        kind="text+pdf",
        file=None,
        text="What is wrong with this part?",
        attachment="d_ctc01_pdf",
    ),
    row("o_logo", "other", "ntsb_16-006"),
]


def write_routes(gold_dir: Path, rows: list[dict], splits: str) -> None:
    (gold_dir / "routes").mkdir(exist_ok=True)
    (gold_dir / "routes" / "routes.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
    )
    (gold_dir / "splits.toml").write_text(splits, encoding="utf-8")


SPLITS = '[router]\ntrain = ["ntsb_16-006"]\ndev = ["ctc01", "text_01"]\ntest = []\n'


def test_a_split_takes_every_case_of_the_units_it_names(gold_dir: Path, settings: Settings) -> None:
    write_routes(gold_dir, ROWS, SPLITS)

    with open_services(settings) as services:
        dev = route_cases(services, "dev")
        train = route_cases(services, "train")

    assert [(c.case_id, c.split, c.stratum) for c in dev] == [
        ("d_ctc01_p1_r72", "dev", "drawing"),
        ("d_ctc01_pdf", "dev", "drawing"),
        ("t_01", "dev", "text"),
        ("tp_01", "dev", "drawing"),
    ]
    assert [(c.case_id, c.stratum) for c in train] == [
        ("o_logo", "other"),
        ("p_16006_x32", "photo"),
    ]


def test_a_case_carries_its_expected_route_and_the_request_to_send(
    gold_dir: Path, settings: Settings
) -> None:
    write_routes(gold_dir, ROWS, SPLITS)

    with open_services(settings) as services:
        cases = {c.case_id: c for c in route_cases(services, "all")}

    assert cases["t_01"].gold["expected_route"] == "text"
    assert cases["t_01"].gold["input"] == {"text": "What failed?", "file": None}
    assert cases["o_logo"].gold["expected_route"] == "other"
    # a message with a file sends the file of the item it names
    assert cases["tp_01"].gold["input"] == {
        "text": "What is wrong with this part?",
        "file": "items/drawing/ctc01.pdf",
    }


def test_the_gold_check_accepts_the_labelled_set(gold_dir: Path, settings: Settings) -> None:
    write_routes(gold_dir, ROWS, SPLITS)

    with open_services(settings) as services:
        found = check_gold(services)

    router = [(level, message) for level, message in found if "router" in message]
    assert ("ok", "router 6 case(s) in 3 unit(s)") in router
    assert [level for level, _ in router if level == "error"] == []


def test_the_gold_check_refuses_a_unit_on_two_sides_and_broken_rows(
    gold_dir: Path, settings: Settings
) -> None:
    rows = [
        *ROWS,
        row("d_ctc01_pdf", "drawing", "ctc01"),
        row("x_odd", "diagram", "ctc01"),
        row("tp_02", "photo", "ctc01", file=None, text="hi", attachment="absent"),
        {"id": "x_bare", "label": "photo"},
    ]
    splits = '[router]\ntrain = ["ctc01"]\ndev = ["ctc01", "text_01"]\ntest = ["ghost"]\n'
    write_routes(gold_dir, rows, splits)

    with open_services(settings) as services:
        found = check_gold(services)

    errors = [message for level, message in found if level == "error"]
    warnings = [message for level, message in found if level == "warning"]
    assert "router ctc01 is in more than one split: train, dev" in errors
    assert "router case id d_ctc01_pdf is used more than once" in errors
    assert (
        "router x_odd has label 'diagram'; use drawing, photo, text or other (fits no case)"
        in errors
    )
    assert "router tp_02 sends the file of 'absent', which is not a case" in errors
    assert "router routes.jsonl line 10 lacks unit" in errors
    assert "router ghost is in the test split but has no gold" in warnings
    assert "router ntsb_16-006 has gold but is in no split" in warnings


def test_the_gold_check_warns_once_when_the_files_are_not_built(
    gold_dir: Path, settings: Settings
) -> None:
    write_routes(gold_dir, ROWS, SPLITS)
    (gold_dir / "routes" / "items" / "drawing").mkdir(parents=True)
    (gold_dir / "routes" / "items" / "drawing" / "ctc01.pdf").write_bytes(b"%PDF-1.7")

    with open_services(settings) as services:
        found = check_gold(services)

    assert (
        "warning",
        "router 3 of 4 file(s) are not in routes/; they are committed, so restore them from git",
    ) in found


def test_a_router_split_that_splits_toml_does_not_name_is_refused(
    gold_dir: Path, settings: Settings
) -> None:
    write_routes(gold_dir, ROWS, SPLITS)

    with (
        open_services(settings) as services,
        pytest.raises(LookupError, match="no router split 'tset'; use dev, test, train or all"),
    ):
        route_cases(services, "tset")


def test_the_gold_check_refuses_a_group_split_across_units_and_a_message_apart_from_its_file(
    gold_dir: Path, settings: Settings
) -> None:
    copy = {**row("d_ctc01_p2_r72", "drawing", "ctc01"), "unit": "ctc01_copy"}
    stray = {**ROWS[4], "id": "tp_02", "group": "text_01", "unit": "text_01"}  # sent with ctc01
    write_routes(gold_dir, [*ROWS, copy, stray], SPLITS)

    with open_services(settings) as services:
        errors = [message for level, message in check_gold(services) if level == "error"]

    assert "router group ctc01 spans units ctc01, ctc01_copy" in errors
    assert "router tp_02 is in unit text_01 but its file d_ctc01_pdf is in ctc01" in errors
