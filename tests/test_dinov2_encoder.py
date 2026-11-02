import os
import threading
import time
from pathlib import Path

import pytest

from resourcly.adapters.dinov2_encoder import Dinov2EncoderAdapter
from resourcly.errors import ModelNotCached
from tests.test_route_pictures import image

torch = pytest.importorskip("torch")


class FakeOutput:
    def __init__(self, pooled):
        self.pooler_output = pooled


class FakeModel:
    """Stands in for DINOv2: its pooled output is [3, 4] whatever the picture."""

    def __call__(self, pixel_values):
        return FakeOutput(torch.tensor([[3.0, 4.0]]))


class FakeProcessor:
    def __init__(self):
        self.sizes: list[tuple[int, int]] = []

    def __call__(self, images, return_tensors):
        self.sizes.append(images.size)
        return {"pixel_values": torch.zeros(1, 3, 2, 2)}


@pytest.fixture(autouse=True)
def nothing_loaded():
    Dinov2EncoderAdapter._loaded.clear()
    Dinov2EncoderAdapter._revisions.clear()
    yield
    Dinov2EncoderAdapter._loaded.clear()
    Dinov2EncoderAdapter._revisions.clear()


def test_the_embedding_is_the_normalised_pooled_output_of_the_picture(tmp_path: Path) -> None:
    processor = FakeProcessor()
    loads: list[str] = []

    def load(path: str):
        loads.append(path)
        return processor, FakeModel(), "cpu"

    first = Dinov2EncoderAdapter("org/dino", locate=lambda _: tmp_path, load=load)
    second = Dinov2EncoderAdapter("org/dino", locate=lambda _: tmp_path, load=load)

    vector = first.encode(image((2048, 1024)))
    second.encode(image((10, 10)))

    assert vector == pytest.approx([0.6, 0.8])
    assert processor.sizes == [(1024, 512), (10, 10)]
    assert loads == [str(tmp_path)]


def test_a_model_that_is_not_cached_is_refused_before_anything_loads() -> None:
    def missing(model_id: str) -> Path:
        raise ModelNotCached(f"{model_id} is not in the local Hugging Face cache")

    encoder = Dinov2EncoderAdapter("org/absent", locate=missing)

    with pytest.raises(ModelNotCached):
        encoder.encode(image((10, 10)))
    assert Dinov2EncoderAdapter._loaded == {}


def test_threads_that_ask_at_once_load_the_model_once(tmp_path: Path) -> None:
    loads: list[str] = []

    def slow_load(path: str):
        time.sleep(0.05)
        loads.append(path)
        return FakeProcessor(), FakeModel(), "cpu"

    encoders = [
        Dinov2EncoderAdapter("org/dino", 64, lambda _: tmp_path, slow_load) for _ in range(4)
    ]
    threads = [threading.Thread(target=e.encode, args=(image((10, 10)),)) for e in encoders]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert loads == [str(tmp_path)]


def test_the_encoder_loads_offline_and_records_the_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    snapshot = tmp_path / "snapshots" / "ed25f3a"
    offline: list[str | None] = []

    def load(path: str):
        offline.append(os.environ.get("HF_HUB_OFFLINE"))
        return FakeProcessor(), FakeModel(), "cpu"

    encoder = Dinov2EncoderAdapter("org/dino", locate=lambda _: snapshot, load=load)
    assert encoder.revision == "not loaded"
    encoder.encode(image((10, 10)))

    assert encoder.revision == "ed25f3a"
    assert offline == ["1"]
