from dataclasses import replace
from pathlib import Path

import pytest

from resourcly import bootstrap
from resourcly.adapters.mlx_vlm_model import MlxVlmModelAdapter
from resourcly.adapters.vlm_readers import VectorCropReaderAdapter, WholePageReaderAdapter
from resourcly.bootstrap import (
    READERS,
    Implementation,
    Settings,
    list_versions,
    load_version,
    open_services,
)
from resourcly.errors import InvalidVersion, ModelNotCached, NotFound
from tests.conftest import CTC01


def _write(settings: Settings, name: str, text: str) -> None:
    path = settings.versions_dir / "reader" / f"{name}.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def versioned(settings: Settings, tmp_path: Path) -> Settings:
    return replace(settings, versions_dir=tmp_path / "versions")


def test_a_version_file_picks_the_reader_the_services_use(versioned: Settings) -> None:
    _write(versioned, "plain", 'description = "text layer only"\nimpl = "textlayer"\n')

    with open_services(versioned.with_version("reader", "plain")) as services:
        reading = services.drawings.read(CTC01)

    assert len(reading.document["values"]) == 6
    assert [(v.component, v.name, v.impl) for v in list_versions(versioned, "reader")] == [
        ("reader", "plain", "textlayer")
    ]


class TunedReader:
    def __init__(self, dpi: int = 150):
        self.dpi = dpi

    def read(self, drawing: str, progress=None) -> dict:
        return {"drawing": drawing, "page_count": 1, "title_block": {}, "values": []}


@pytest.fixture
def tunable(monkeypatch: pytest.MonkeyPatch) -> None:
    tuned = Implementation(lambda settings, params: TunedReader(**params), settings=("dpi",))
    monkeypatch.setitem(READERS, "tuned", tuned)


def test_the_hash_follows_the_settings_not_the_name_or_description(
    versioned: Settings, tunable: None
) -> None:
    _write(versioned, "a", 'impl = "tuned"\n')
    _write(versioned, "b", 'description = "same reader"\nimpl = "tuned"\n')
    _write(versioned, "c", 'impl = "tuned"\ndpi = 200\n')

    a, b, c = (load_version(versioned, "reader", name) for name in "abc")

    assert a.hash == b.hash != c.hash
    assert c.params == {"dpi": 200}


def test_unknown_versions_and_implementations_are_refused(versioned: Settings) -> None:
    _write(versioned, "odd", 'impl = "vlm"\n')

    with pytest.raises(NotFound, match="no reader version 'absent'"):
        load_version(versioned, "reader", "absent")
    with pytest.raises(
        InvalidVersion,
        match="'vlm' is not a reader implementation; use textlayer, vector-crop, whole-page",
    ):
        load_version(versioned, "reader", "odd")


def test_a_version_passes_its_settings_to_the_implementation(
    versioned: Settings, tunable: None
) -> None:
    _write(versioned, "sharp", 'impl = "tuned"\ndpi = 300\n')

    with open_services(versioned.with_version("reader", "sharp")) as services:
        assert services.drawings.reader.dpi == 300


def test_a_setting_the_implementation_does_not_take_is_refused(versioned: Settings) -> None:
    _write(versioned, "typo", 'impl = "textlayer"\nmin_words = 3\n')

    with pytest.raises(
        InvalidVersion, match="reader version 'typo': textlayer takes no setting min_words"
    ):
        load_version(versioned, "reader", "typo")


def test_the_committed_default_versions_exist() -> None:
    settings = Settings()
    for component, impl in (
        ("reader", "vector-crop"),
        ("router", "three-layer"),
        ("failure", "shuffled"),
    ):
        assert load_version(settings, component, settings.versions[component]).impl == impl


def test_gold_work_needs_no_reader_version_or_trace_file(
    settings: Settings, tmp_path: Path
) -> None:
    bare = replace(settings, versions_dir=tmp_path / "no-versions")

    with open_services(bare) as services:
        assert services.gold.list_drawings()
        assert not bare.trace_path.exists()
        with pytest.raises(NotFound, match="no reader version 'textlayer-v0'"):
            services.drawings.read(CTC01)


@pytest.mark.parametrize(
    ("name", "reader"),
    [
        ("vector-crop-v1", VectorCropReaderAdapter),
        ("vector-crop-v2", VectorCropReaderAdapter),
        ("whole-page-v1", WholePageReaderAdapter),
    ],
)
def test_the_vlm_versions_build_their_reader_without_loading_the_model(
    settings: Settings, name: str, reader: type
) -> None:
    version = load_version(settings, "reader", name)
    built = READERS[version.impl].build(settings, version.params)

    assert isinstance(built, reader)
    assert isinstance(built.model, MlxVlmModelAdapter)
    assert built.model.model_id == "mlx-community/Qwen3-VL-8B-Instruct-4bit"
    assert built.prompt.startswith("This ")
    assert built.model.model_id not in MlxVlmModelAdapter._loaded


@pytest.mark.parametrize(
    ("text", "missing"),
    [
        ('impl = "vector-crop"\nprompt = "read"\n', "model"),
        ('impl = "whole-page"\nmodel = "org/model"\n', "prompt"),
    ],
)
def test_a_vlm_version_without_its_model_or_prompt_is_refused(
    versioned: Settings, text: str, missing: str
) -> None:
    _write(versioned, "incomplete", text)

    with pytest.raises(InvalidVersion, match=f"needs the setting {missing}"):
        load_version(versioned, "reader", "incomplete")


def _read_with_model(settings: Settings, model: str) -> str:
    """The error a vision reader whose model is `model` gives when it reads CTC-01."""
    _write(settings, "absent", f'impl = "vector-crop"\nmodel = "{model}"\nprompt = "p"\n')
    with open_services(settings.with_version("reader", "absent")) as services:
        with pytest.raises(ModelNotCached) as raised:
            services.drawings.read(CTC01)
    return str(raised.value)


def test_a_model_that_is_not_cached_says_how_to_download_it_or_fall_back(
    versioned: Settings,
) -> None:
    pytest.importorskip("huggingface_hub")

    message = _read_with_model(versioned, "org/absent")

    assert "org/absent is not in the local Hugging Face cache" in message
    assert "hf download org/absent" in message
    assert "RESOURCLY_READER_VERSION=textlayer-v0" in message


def test_a_machine_without_the_vlm_extra_says_how_to_install_it_or_fall_back(
    versioned: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(bootstrap, "find_spec", lambda name: None)

    message = _read_with_model(versioned, "org/model")

    assert "uv sync --extra vlm" in message
    assert "RESOURCLY_READER_VERSION=textlayer-v0" in message


def test_vector_crop_v2_is_v1_plus_the_whole_page_fallback(settings: Settings) -> None:
    v1, v2, page = (
        load_version(settings, "reader", name).params
        for name in ("vector-crop-v1", "vector-crop-v2", "whole-page-v1")
    )

    assert {k: v for k, v in v2.items() if not k.startswith("page_")} == v1
    assert (v2["page_prompt"], v2["page_dpi"], v2["page_max_tokens"]) == (
        page["prompt"],
        page["dpi"],
        page["max_tokens"],
    )
