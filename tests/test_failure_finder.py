import logging

import pytest

from resourcly.adapters.shuffled_figures import ShuffledFiguresAdapter
from resourcly.bootstrap import PROJECT_ROOT, Settings, open_services
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

    def find(self, photo: Attachment) -> list[FigureMatch]:
        if isinstance(self.found, Exception):
            raise self.found
        return self.found


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


def test_the_service_returns_the_ranked_figures_and_traces_the_call() -> None:
    trace = MemoryTrace()

    matches = FailureService(FakeFinder([FATIGUE]), trace, "v1 (fake)").find(PHOTO, "req-1")

    assert (matches.request_id, matches.figures) == ("req-1", [FATIGUE])
    assert matches.elapsed_ms >= 0
    [event] = trace.find("req-1")
    assert (event.step, event.called, event.error) == ("failure.find", "finder v1 (fake)", None)
    assert event.input["photo"]["name"] == "crack.png"
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
