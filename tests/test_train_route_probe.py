import json
from pathlib import Path

import pytest

from resourcly.adapters.route_probe import LinearProbe
from resourcly.bootstrap import Settings, open_services
from tests.eval_harness.test_route_gold import row, write_routes

pytest.importorskip("sklearn")

from train_route_probe import train, training_cases  # noqa: E402

ROWS = [
    row("d_a", "drawing", "ctc01"),
    row("d_b", "drawing", "ctc01"),
    row("d_c", "drawing", "ftc06"),
    row("p_a", "photo", "ntsb_16-006"),
    row("p_b", "photo", "ntsb_16-006"),
    row("tp_a", "photo", "ntsb_16-006", kind="text+image", text="what broke?", attachment="p_a"),
    row("o_logo", "other", "ntsb_16-006"),
    row("t_01", "text", "text_01", kind="text", file=None, text="hi"),
    row("d_dev", "drawing", "ctc02"),
]
SPLITS = '[router]\ntrain = ["ctc01", "ftc06", "ntsb_16-006", "text_01"]\ndev = ["ctc02"]\n'


class FakeEncoder:
    """Each route embeds to its own axis, read from the folder in the file name."""

    model_id = "org/encoder"

    def encode(self, attachment) -> list[float]:
        return [float(f"/{route}/" in attachment.name) for route in ("drawing", "other", "photo")]


@pytest.fixture
def routed(gold_dir: Path, settings: Settings) -> Settings:
    write_routes(gold_dir, ROWS, SPLITS)
    for r in ROWS:
        if r["file"]:
            path = gold_dir / "routes" / r["file"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"\x89PNG\r\n\x1a\n")
    return settings


def test_the_probe_trains_on_every_file_of_the_split_that_fits_or_fits_no_case(
    routed: Settings,
) -> None:
    with open_services(routed) as services:
        cases = training_cases(services, "train")

    assert [case.case_id for case in cases] == ["d_a", "d_b", "d_c", "o_logo", "p_a", "p_b"]


def test_a_trained_probe_records_what_it_was_trained_on_and_separates_the_cases(
    routed: Settings, tmp_path: Path
) -> None:
    with open_services(routed) as services:
        document = train(services, FakeEncoder(), "train", c=100.0)

    assert document["encoder_model"] == "org/encoder"
    assert document["classes"] == ["drawing", "other", "photo"]
    assert document["regression"] == {"C": 100.0, "class_weight": "balanced"}
    assert document["trained_on"]["split"] == "train"
    assert document["trained_on"]["cases"] == {"drawing": 3, "other": 1, "photo": 2}
    assert document["trained_on"]["units"] == ["ctc01", "ftc06", "ntsb_16-006"]
    path = tmp_path / "probe.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    probe = LinearProbe.load(path)
    for axis, route in enumerate(("drawing", "other", "photo")):
        vector = [float(i == axis) for i in range(3)]
        assert probe.probabilities(vector)[route] > 0.9


def test_a_split_without_a_file_of_every_route_cannot_train(routed: Settings) -> None:
    with (
        open_services(routed) as services,
        pytest.raises(SystemExit, match="no other or photo file in the dev split"),
    ):
        train(services, FakeEncoder(), "dev", c=100.0)
