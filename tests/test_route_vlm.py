import math
import os
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from resourcly.adapters.mlx_vlm_model import (
    MlxVlmModelAdapter,
    option_mass,
    option_probabilities,
)
from resourcly.adapters.route_vlm import VlmRouteAdapter
from resourcly.errors import ModelNotCached
from resourcly.models import Choice, Route
from tests.test_route_pictures import image


class FakeVisionModel:
    model_id = "org/vlm"
    revision = "abc123"

    def __init__(self, answer: dict[str, float], mass: float = 0.98):
        self.answer = answer
        self.mass = mass
        self.calls: list[tuple[str, list[bytes], list[str]]] = []

    def choose(self, prompt: str, images: list[bytes], options: list[str]) -> Choice:
        self.calls.append((prompt, images, options))
        return Choice(self.answer, self.mass)


def test_the_model_picks_one_of_three_letters_for_the_picture() -> None:
    model = FakeVisionModel({"A": 0.96, "B": 0.03, "C": 0.01})

    verdict = VlmRouteAdapter(model, "Which one? A, B or C").decide(image((2000, 1000)))

    assert verdict.route == Route.DRAWING
    assert verdict.confidence == pytest.approx(0.96)
    assert verdict.probabilities == {"drawing": 0.96, "photo": 0.03, "other": 0.01}
    assert verdict.reason == (
        "org/vlm answers A (drawing) at 0.960; the letters hold 0.980 of the first token"
    )
    [(prompt, [png], options)] = model.calls
    assert (prompt, options) == ("Which one? A, B or C", ["A", "B", "C"])
    with Image.open(BytesIO(png)) as seen:
        assert (seen.format, seen.size) == ("PNG", (768, 384))


def test_something_else_is_a_file_that_fits_no_case() -> None:
    model = FakeVisionModel({"A": 0.2, "B": 0.1, "C": 0.7})

    verdict = VlmRouteAdapter(model, "q").decide(image((50, 50)))

    assert (verdict.route, verdict.reason) == (
        Route.OTHER,
        "org/vlm answers C (other) at 0.700; the letters hold 0.980 of the first token",
    )


def test_the_model_has_nothing_to_judge_without_an_attachment() -> None:
    model = FakeVisionModel({"A": 1.0, "B": 0.0, "C": 0.0})

    assert VlmRouteAdapter(model, "q").decide(None).route is None
    assert model.calls == []


def test_option_probabilities_are_the_first_token_scores_normalised_over_the_options() -> None:
    probabilities = option_probabilities([-0.1, -2.5, -9.0])

    assert sum(probabilities) == pytest.approx(1.0)
    assert probabilities[0] > 0.9 > probabilities[1] > probabilities[2]
    assert option_probabilities([-1000.0, -1001.0]) == pytest.approx([0.7311, 0.2689], abs=1e-4)


def test_choosing_refuses_a_model_that_is_not_cached_before_loading_it() -> None:
    def missing(model_id: str) -> Path:
        raise ModelNotCached(f"{model_id} is not in the local Hugging Face cache")

    adapter = MlxVlmModelAdapter("org/absent", locate=missing)

    with pytest.raises(ModelNotCached):
        adapter.choose("q", [], ["A", "B"])
    assert "org/absent" not in MlxVlmModelAdapter._loaded


def test_the_letters_share_of_the_first_token_is_their_summed_probability() -> None:
    assert option_mass([math.log(0.5), math.log(0.3), math.log(0.1)]) == pytest.approx(0.9)


def test_the_trace_names_the_model_snapshot() -> None:
    layer = VlmRouteAdapter(FakeVisionModel({"A": 1.0}), "q")

    assert layer.called == "org/vlm (snapshot abc123), one multiple-choice question"


def test_the_adapter_loads_offline_and_records_the_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    snapshot = tmp_path / "snapshots" / "abc123"
    offline: list[str | None] = []

    def load(path: str) -> tuple[object, object]:
        offline.append(os.environ.get("HF_HUB_OFFLINE"))
        return object(), object()

    adapter = MlxVlmModelAdapter("org/offline-model", locate=lambda _: snapshot, load=load)
    try:
        assert adapter.revision == "not loaded"
        adapter._load()
        assert adapter.revision == "abc123"
    finally:
        MlxVlmModelAdapter._loaded.clear()
        MlxVlmModelAdapter._revisions.clear()

    assert offline == ["1"]
