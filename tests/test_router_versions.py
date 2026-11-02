import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from resourcly.adapters.dinov2_encoder import Dinov2EncoderAdapter
from resourcly.adapters.mlx_vlm_model import MlxVlmModelAdapter
from resourcly.adapters.route_probe import ProbeRouteAdapter
from resourcly.adapters.route_structure import StructureRouteAdapter
from resourcly.adapters.route_vlm import VlmRouteAdapter
from resourcly.bootstrap import (
    PROJECT_ROOT,
    Settings,
    load_version,
    open_services,
    vision_model,
)
from resourcly.errors import InvalidVersion
from resourcly.models import Route
from resourcly.services import RouterService
from tests.test_route_pictures import truncated_jpeg

COMMITTED = PROJECT_ROOT / "versions" / "router"


@pytest.fixture
def layered(settings: Settings) -> Settings:
    """Settings that run the committed three-layer router."""
    return settings.with_version("router", "three-layer-v1")


@pytest.fixture
def versioned(layered: Settings, tmp_path: Path) -> Settings:
    """The committed router versions and probes, copied so a test can edit them."""
    shutil.copytree(COMMITTED, tmp_path / "versions" / "router")
    return replace(layered, versions_dir=tmp_path / "versions")


def test_the_three_layer_version_names_its_models_and_threshold(layered: Settings) -> None:
    version = load_version(layered, "router", layered.versions["router"])

    assert (version.name, version.impl) == ("three-layer-v1", "three-layer")
    assert version.params["threshold"] == 0.9
    assert version.params["encoder_model"] == "facebook/dinov2-small"
    assert version.params["model"] == "mlx-community/Qwen3-VL-8B-Instruct-4bit"


def test_the_version_builds_the_three_layers_without_loading_a_model(layered: Settings) -> None:
    with open_services(layered) as services:
        router = services.router

    assert isinstance(router, RouterService)
    structure, probe, vlm = router.layers
    assert isinstance(structure, StructureRouteAdapter) and structure.vector_paths == 300
    assert isinstance(probe, ProbeRouteAdapter) and probe.threshold == 0.9
    assert isinstance(probe.encoder, Dinov2EncoderAdapter)
    assert (probe.encoder.model_id, probe.encoder.max_side) == ("facebook/dinov2-small", 1024)
    assert isinstance(vlm, VlmRouteAdapter) and vlm.max_side == 768
    assert isinstance(vlm.model, MlxVlmModelAdapter)
    assert vlm.prompt.startswith("Which one best describes this image?")
    assert router.router_name == "three-layer-v1 (three-layer)"
    assert Dinov2EncoderAdapter._loaded == {}


def test_a_text_question_is_routed_and_traced_without_any_model(layered: Settings) -> None:
    with open_services(layered) as services:
        routing = services.router.route("What caused the crack?", None, request_id="q-1")
        [event] = services.traces.lookup("q-1").events

    assert (routing.route, routing.layer, routing.reason) == (
        Route.TEXT,
        "structure",
        "no attachment",
    )
    assert event.step == "route.structure"
    assert event.called.startswith("router three-layer-v1 (three-layer): PyMuPDF structure rules")


def test_the_probe_file_is_part_of_the_version_hash(versioned: Settings) -> None:
    before = load_version(versioned, "router", "three-layer-v1")
    probe = versioned.versions_dir / "router" / before.params["probe"]
    probe.write_text(probe.read_text(encoding="utf-8").replace('"bias": ', '"bias": 1 + '))

    after = load_version(versioned, "router", "three-layer-v1")

    assert set(before.files) == {"probe"}
    assert before.files != after.files
    assert before.hash != after.hash


def test_a_version_whose_probe_file_is_missing_is_refused(versioned: Settings) -> None:
    version = load_version(versioned, "router", "three-layer-v1")
    (versioned.versions_dir / "router" / version.params["probe"]).unlink()

    with pytest.raises(InvalidVersion, match="names the probe file probes/dinov2-small-v1.json"):
        load_version(versioned, "router", "three-layer-v1")


def test_a_probe_trained_on_another_encoder_is_refused_when_the_router_is_built(
    versioned: Settings,
) -> None:
    path = versioned.versions_dir / "router" / "three-layer-v1.toml"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            'encoder_model = "facebook/dinov2-small"', 'encoder_model = "facebook/dinov2-base"'
        ),
        encoding="utf-8",
    )

    with open_services(versioned) as services, pytest.raises(InvalidVersion, match="dinov2-base"):
        services.router  # noqa: B018


def test_an_encoder_the_registry_does_not_know_is_refused(versioned: Settings) -> None:
    path = versioned.versions_dir / "router" / "three-layer-v1.toml"
    path.write_text(
        path.read_text(encoding="utf-8").replace('encoder = "dinov2"', 'encoder = "clip"'),
        encoding="utf-8",
    )

    with pytest.raises(InvalidVersion, match="'clip' is not an image encoder; use dinov2"):
        load_version(versioned, "router", "three-layer-v1")


def test_a_truncated_photo_is_routed_to_other_instead_of_failing_the_request(
    layered: Settings,
) -> None:
    with open_services(layered) as services:
        routing = services.router.route(None, truncated_jpeg(), request_id="cut-1")

    assert (routing.route, routing.layer) == (Route.OTHER, "probe")
    assert routing.reason.startswith("not a readable image/jpeg image")
    assert Dinov2EncoderAdapter._loaded == {}


def test_the_reader_and_the_router_share_one_adapter_of_their_vision_model(
    layered: Settings,
) -> None:
    settings = layered.with_version("reader", "vector-crop-v2")
    with open_services(settings) as services:
        reader_model = services.drawings.reader.model
        router_model = services.router.layers[2].model
        again = services._drawings_in(settings.drawings_dir).reader.model

    assert reader_model is router_model is again
    assert vision_model("mlx-community/Qwen3-VL-8B-Instruct-4bit") is reader_model
    assert reader_model.revision == "not loaded"
    assert vision_model("org/other") is not reader_model
