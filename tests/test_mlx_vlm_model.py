import threading
import time
from pathlib import Path

import pytest

from resourcly.adapters.mlx_vlm_model import MlxVlmModelAdapter, cached_snapshot
from resourcly.errors import ModelNotCached

MODEL = "mlx-community/Qwen3-VL-8B-Instruct-4bit"


def _fake_cache(root: Path, model_id: str) -> Path:
    """A Hugging Face cache folder holding one snapshot of the model, as a download leaves it."""
    folder = root / f"models--{model_id.replace('/', '--')}"
    snapshot = folder / "snapshots" / "abc123"
    snapshot.mkdir(parents=True)
    (snapshot / "config.json").write_text("{}")
    (folder / "refs").mkdir()
    (folder / "refs" / "main").write_text("abc123")
    return snapshot


def test_a_cached_model_resolves_to_its_local_snapshot(tmp_path: Path) -> None:
    pytest.importorskip("huggingface_hub")
    snapshot = _fake_cache(tmp_path, MODEL)

    assert cached_snapshot(MODEL, cache_dir=tmp_path) == snapshot


def test_a_model_that_is_not_cached_is_refused_without_a_download(tmp_path: Path) -> None:
    pytest.importorskip("huggingface_hub")

    with pytest.raises(ModelNotCached, match="org/absent is not in the local Hugging Face cache"):
        cached_snapshot("org/absent", cache_dir=tmp_path)


def test_a_local_folder_is_used_as_it_is(tmp_path: Path) -> None:
    assert cached_snapshot(str(tmp_path)) == tmp_path


def test_the_adapter_refuses_before_it_loads_anything_when_the_model_is_missing() -> None:
    def missing(model_id: str) -> Path:
        raise ModelNotCached(f"{model_id} is not in the local Hugging Face cache")

    adapter = MlxVlmModelAdapter("org/absent", locate=missing)

    with pytest.raises(ModelNotCached):
        adapter.generate("prompt", [], 10)
    assert "org/absent" not in MlxVlmModelAdapter._loaded


def test_the_adapter_loads_the_model_from_the_resolved_folder(tmp_path: Path) -> None:
    loaded: list[str] = []

    def load(path: str) -> tuple[object, object]:
        loaded.append(path)
        return object(), object()

    adapter = MlxVlmModelAdapter("org/model", locate=lambda _: tmp_path, load=load)
    try:
        adapter._load()
        adapter._load()
    finally:
        MlxVlmModelAdapter._loaded.clear()

    assert loaded == [str(tmp_path)]


def test_threads_that_ask_at_once_load_the_model_once(tmp_path: Path) -> None:
    loaded: list[str] = []

    def slow_load(path: str) -> tuple[object, object]:
        time.sleep(0.05)
        loaded.append(path)
        return object(), object()

    adapters = [MlxVlmModelAdapter("org/model", lambda _: tmp_path, slow_load) for _ in range(4)]
    try:
        threads = [threading.Thread(target=adapter._load) for adapter in adapters]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
    finally:
        MlxVlmModelAdapter._loaded.clear()

    assert loaded == [str(tmp_path)]
