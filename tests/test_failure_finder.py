import logging
import shutil
from collections.abc import Collection
from dataclasses import replace
from pathlib import Path

import pytest

from resourcly.adapters.dinov2_encoder import Dinov2EncoderAdapter
from resourcly.adapters.nearest_figures import NearestFiguresAdapter
from resourcly.adapters.shuffled_figures import ShuffledFiguresAdapter
from resourcly.bootstrap import FINDERS, PROJECT_ROOT, Settings, load_version, open_services
from resourcly.errors import InvalidVersion
from resourcly.models import Attachment, FigureMatch, TraceEvent
from resourcly.services import FailureService
from tests.conftest import png

SECTIONS = PROJECT_ROOT / "data" / "reports" / "sections.toml"
PHOTO = Attachment("crack.png", "image/png", png())
FATIGUE = FigureMatch(
    figure="18-061/fig06",
    report="18-061",
    section="spar_fatigue_N106ER",
    failure_mode="fatigue",
    score=0.91,
)


class FakeFinder:
    def __init__(self, found: list[FigureMatch] | Exception):
        self.found = found
        self.excluded: list[set[str]] = []

    def find(self, photo: Attachment, exclude: Collection[str] = ()) -> list[FigureMatch]:
        self.excluded.append(set(exclude))
        if isinstance(self.found, Exception):
            raise self.found
        return [match for match in self.found if match.figure not in exclude]


class MemoryTrace:
    def __init__(self, fail: bool = False):
        self.events: list[TraceEvent] = []
        self.fail = fail

    def record(self, event: TraceEvent) -> None:
        if self.fail:
            raise OSError("disk full")
        self.events.append(event)

    def find(self, request_id: str) -> list[TraceEvent]:
        return [event for event in self.events if event.request_id == request_id]


def test_the_shuffled_baseline_ranks_every_report_figure_the_same_way_for_any_photo() -> None:
    finder = ShuffledFiguresAdapter(SECTIONS, seed=0)

    first = finder.find(PHOTO)
    again = finder.find(Attachment("other.jpg", "image/jpeg", b"\xff\xd8\xffdata"))

    assert len(first) == 46
    assert {match.report for match in first} == {"16-006", "18-061", "24-013"}
    assert first == again
    assert [match.figure for match in first] != sorted(match.figure for match in first)
    fig06 = next(match for match in first if match.figure == "18-061/fig06")
    assert (fig06.section, fig06.failure_mode, fig06.score) == (
        "spar_fatigue_N106ER",
        "fatigue",
        None,
    )


def test_the_seed_picks_the_order() -> None:
    orders = [
        [match.figure for match in ShuffledFiguresAdapter(SECTIONS, seed=seed).find(PHOTO)]
        for seed in (0, 0, 1)
    ]

    assert orders[0] == orders[1] != orders[2]


def test_the_shuffled_baseline_leaves_out_a_hidden_figure() -> None:
    finder = ShuffledFiguresAdapter(SECTIONS, seed=0)

    found = [match.figure for match in finder.find(PHOTO, exclude={"18-061/fig06"})]

    assert found == [m.figure for m in finder.find(PHOTO) if m.figure != "18-061/fig06"]
    assert len(found) == 45


def test_the_service_passes_the_hidden_figures_to_the_finder_and_traces_them() -> None:
    trace, finder = MemoryTrace(), FakeFinder([FATIGUE])

    matches = FailureService(finder, trace, "v1").find(PHOTO, "req-5", exclude={"18-061/fig06"})

    assert (matches.figures, finder.excluded) == ([], [{"18-061/fig06"}])
    assert trace.find("req-5")[0].input["exclude"] == ["18-061/fig06"]


def test_the_service_returns_the_ranked_figures_and_traces_the_call() -> None:
    trace = MemoryTrace()

    matches = FailureService(FakeFinder([FATIGUE]), trace, "v1 (fake)").find(PHOTO, "req-1")

    assert (matches.request_id, matches.figures) == ("req-1", [FATIGUE])
    assert matches.elapsed_ms >= 0
    [event] = trace.find("req-1")
    assert (event.step, event.called, event.error) == ("failure.find", "finder v1 (fake)", None)
    assert event.input["photo"]["name"] == "crack.png"
    assert "exclude" not in event.input
    assert event.output == {"figures": 1, "top": "18-061/fig06"}


def test_a_photo_that_matches_no_report_gets_no_figure() -> None:
    trace = MemoryTrace()

    matches = FailureService(FakeFinder([]), trace, "v1").find(PHOTO, "req-2")

    assert matches.figures == []
    assert trace.find("req-2")[0].output == {"figures": 0, "top": None}


def test_a_failing_finder_is_traced_with_its_error_and_raised() -> None:
    trace = MemoryTrace()

    with pytest.raises(RuntimeError, match="no GPU"):
        FailureService(FakeFinder(RuntimeError("no GPU")), trace, "v1").find(PHOTO, "req-3")

    assert trace.find("req-3")[0].error == "RuntimeError: no GPU"


def test_a_trace_that_cannot_be_recorded_does_not_change_the_answer(
    caplog: pytest.LogCaptureFixture,
) -> None:
    service = FailureService(FakeFinder([FATIGUE]), MemoryTrace(fail=True), "v1")

    with caplog.at_level(logging.ERROR):
        matches = service.find(PHOTO, "req-4")

    assert matches.figures == [FATIGUE]
    assert "could not record the trace of request req-4" in caplog.text


def test_the_baseline_version_finds_without_a_model(settings: Settings) -> None:
    with open_services(settings.with_version("failure", "shuffled-v0")) as services:
        matches = services.failures.find(PHOTO, "r1")
        steps = [event.step for event in services.traces.lookup("r1").events]

    assert len(matches.figures) == 46
    assert steps == ["failure.find"]


@pytest.mark.parametrize(
    ("name", "model", "size"),
    [
        ("dinov2-base-v1", "facebook/dinov2-base", 1536),
        ("dinov2-small-v1", "facebook/dinov2-small", 768),
    ],
)
def test_the_dinov2_versions_build_their_finder_without_loading_a_model(
    settings: Settings, name: str, model: str, size: int
) -> None:
    version = load_version(settings, "failure", name)
    finder = FINDERS[version.impl].build(settings, version.params)

    assert isinstance(finder, NearestFiguresAdapter)
    assert isinstance(finder.encoder, Dinov2EncoderAdapter)
    assert (finder.encoder.model_id, finder.encoder.recipe, finder.encoder.input_size) == (
        model,
        "cls_patch_mean",
        224,
    )
    assert finder.encoder.revision == "not loaded"
    assert (finder.threshold, finder.top) == (0.28, 5)
    assert len(finder.index.figures) == 46
    assert {len(figure.vector) for figure in finder.index.figures} == {size}
    assert "index" in version.files


def test_a_finder_version_whose_index_was_made_with_another_model_is_refused(
    settings: Settings, tmp_path: Path
) -> None:
    folder = tmp_path / "versions" / "failure"
    shutil.copytree(PROJECT_ROOT / "versions" / "failure", folder)
    text = (folder / "dinov2-base-v1.toml").read_text(encoding="utf-8")
    (folder / "mixed.toml").write_text(
        text.replace('"indexes/dinov2-base-v1.json"', '"indexes/dinov2-small-v1.json"'),
        encoding="utf-8",
    )
    versioned = replace(settings, versions_dir=tmp_path / "versions")
    version = load_version(versioned, "failure", "mixed")

    with pytest.raises(InvalidVersion, match="made with facebook/dinov2-small"):
        FINDERS[version.impl].build(versioned, version.params)


def test_a_finder_version_with_an_unknown_encoder_is_refused(
    settings: Settings, tmp_path: Path
) -> None:
    folder = tmp_path / "versions" / "failure"
    shutil.copytree(PROJECT_ROOT / "versions" / "failure", folder)
    text = (folder / "dinov2-base-v1.toml").read_text(encoding="utf-8")
    (folder / "clip.toml").write_text(text.replace('"dinov2"', '"clip"', 1), encoding="utf-8")

    with pytest.raises(InvalidVersion, match="'clip' is not an image encoder"):
        load_version(replace(settings, versions_dir=tmp_path / "versions"), "failure", "clip")
