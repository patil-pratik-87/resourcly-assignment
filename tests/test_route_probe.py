import json
import math
from pathlib import Path

import pytest

from resourcly.adapters.route_probe import LinearProbe, ProbeRouteAdapter
from resourcly.errors import InvalidVersion, UnreadableAttachment
from resourcly.models import Attachment, Route

PICTURE = Attachment("part.png", "image/png", b"\x89PNG\r\n\x1a\n")
CLASSES = ("drawing", "other", "photo")


class FakeEncoder:
    """Returns a fixed embedding, so a test sets the probe's answer through the weights."""

    model_id = "org/encoder"
    revision = "def456"

    def __init__(self, vector: list[float]):
        self.vector = vector
        self.seen: list[Attachment] = []

    def encode(self, attachment: Attachment) -> list[float]:
        self.seen.append(attachment)
        return self.vector


def probe_for(drawing: float, other: float, photo: float) -> LinearProbe:
    """A one-weight probe that gives the embedding [1.0] these probabilities."""
    return LinearProbe(
        encoder_model="org/encoder",
        classes=CLASSES,
        weights=((math.log(drawing),), (math.log(other),), (math.log(photo),)),
        bias=(0.0, 0.0, 0.0),
    )


def test_a_sure_probe_decides_and_gives_every_probability() -> None:
    encoder = FakeEncoder([1.0])
    layer = ProbeRouteAdapter(encoder, probe_for(0.97, 0.01, 0.02), threshold=0.9)

    verdict = layer.decide(PICTURE)

    assert verdict.route == Route.DRAWING
    assert verdict.confidence == pytest.approx(0.97)
    assert verdict.probabilities == pytest.approx({"drawing": 0.97, "other": 0.01, "photo": 0.02})
    assert verdict.reason == "the probe gives drawing 0.970"
    assert encoder.seen == [PICTURE]


def test_a_high_photo_probability_is_a_photo() -> None:
    verdict = ProbeRouteAdapter(FakeEncoder([1.0]), probe_for(0.01, 0.01, 0.98), 0.9).decide(
        PICTURE
    )

    assert (verdict.route, verdict.reason) == (Route.PHOTO, "the probe gives photo 0.980")


def test_a_probe_sure_the_file_fits_no_case_routes_it_to_other() -> None:
    verdict = ProbeRouteAdapter(FakeEncoder([1.0]), probe_for(0.03, 0.95, 0.02), 0.9).decide(
        PICTURE
    )

    assert (verdict.route, verdict.reason) == (Route.OTHER, "the probe gives other 0.950")


def test_an_unsure_probe_passes_the_request_on_with_its_guess() -> None:
    verdict = ProbeRouteAdapter(FakeEncoder([1.0]), probe_for(0.83, 0.12, 0.05), 0.9).decide(
        PICTURE
    )

    assert verdict.route is None
    assert verdict.confidence == pytest.approx(0.83)
    assert verdict.reason == "the probe gives drawing 0.830, below 0.9"


def test_the_probe_has_nothing_to_judge_without_an_attachment() -> None:
    encoder = FakeEncoder([1.0])

    verdict = ProbeRouteAdapter(encoder, probe_for(0.97, 0.01, 0.02), 0.9).decide(None)

    assert verdict.route is None
    assert encoder.seen == []


def test_a_probe_trained_on_another_encoder_is_refused() -> None:
    probe = LinearProbe("org/other", ("drawing", "photo"), ((1.0,), (0.0,)), (0.0, 0.0))

    with pytest.raises(InvalidVersion, match="trained on org/other embeddings, not org/encoder"):
        ProbeRouteAdapter(FakeEncoder([1.0]), probe, 0.9)


def test_an_embedding_of_the_wrong_size_is_an_error() -> None:
    layer = ProbeRouteAdapter(FakeEncoder([1.0, 0.0]), probe_for(0.9, 0.05, 0.05), 0.9)

    with pytest.raises(ValueError, match="2 numbers, the probe takes 1"):
        layer.decide(PICTURE)


def write_probe(path: Path, **fields) -> Path:
    document = {
        "encoder_model": "org/encoder",
        "classes": ["drawing", "other", "photo"],
        "weights": [[0.5, -0.25], [0.0, 0.0], [-0.5, 0.25]],
        "bias": [0.1, 0.0, -0.1],
        "trained_on": {"split": "train", "cases": {"drawing": 1, "other": 1, "photo": 1}},
        **fields,
    }
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def test_a_probe_loads_from_its_json_file(tmp_path: Path) -> None:
    probe = LinearProbe.load(write_probe(tmp_path / "probe.json"))

    assert probe == LinearProbe(
        "org/encoder",
        CLASSES,
        ((0.5, -0.25), (0.0, 0.0), (-0.5, 0.25)),
        (0.1, 0.0, -0.1),
    )
    scores = [1.1, 0.0, -1.1]
    total = sum(math.exp(score) for score in scores)
    expected = {name: math.exp(s) / total for name, s in zip(CLASSES, scores, strict=True)}
    assert probe.probabilities([2.0, 0.0]) == pytest.approx(expected)
    assert probe.probabilities([1e6, 0.0])["drawing"] == pytest.approx(1.0)


def test_a_probe_file_without_weights_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "probe.json"
    path.write_text('{"encoder_model": "org/encoder"}', encoding="utf-8")

    with pytest.raises(
        InvalidVersion, match="probe.json is not a probe: it lacks classes, weights, bias"
    ):
        LinearProbe.load(path)


def test_a_probe_whose_classes_are_not_routes_is_refused(tmp_path: Path) -> None:
    path = write_probe(tmp_path / "probe.json", classes=["drawing", "cat", "photo"])

    with pytest.raises(InvalidVersion, match="probe.json names cat, which is not a route"):
        LinearProbe.load(path)


def test_a_probe_whose_weights_do_not_match_its_classes_is_refused(tmp_path: Path) -> None:
    path = write_probe(tmp_path / "probe.json", bias=[0.1, 0.0])

    with pytest.raises(InvalidVersion, match="3 classes, 3 weight rows and 2 biases"):
        LinearProbe.load(path)


def test_the_trace_names_the_encoder_snapshot() -> None:
    layer = ProbeRouteAdapter(FakeEncoder([1.0]), probe_for(0.9, 0.05, 0.05), 0.9)

    assert layer.called == "linear probe on org/encoder (snapshot def456), deciding at 0.9"


class UnreadableEncoder(FakeEncoder):
    def encode(self, attachment: Attachment) -> list[float]:
        raise UnreadableAttachment("not a readable image/jpeg image: image file is truncated")


def test_a_file_the_encoder_cannot_read_fits_no_case() -> None:
    layer = ProbeRouteAdapter(UnreadableEncoder([1.0]), probe_for(0.9, 0.05, 0.05), 0.9)

    verdict = layer.decide(PICTURE)

    assert (verdict.route, verdict.confidence) == (Route.OTHER, 1.0)
    assert verdict.reason == "not a readable image/jpeg image: image file is truncated"
