import hashlib
import logging

import pytest

from resourcly.models import Attachment, LayerVerdict, Route, TraceEvent
from resourcly.services import RouterService

PHOTO = Attachment("part.jpg", "image/jpeg", b"\xff\xd8\xffdata")


class FakeLayer:
    def __init__(self, name: str, verdict: LayerVerdict | Exception):
        self.name = name
        self.called = f"fake {name}"
        self.verdict = verdict
        self.seen: list[Attachment | None] = []

    def decide(self, attachment: Attachment | None) -> LayerVerdict:
        self.seen.append(attachment)
        if isinstance(self.verdict, Exception):
            raise self.verdict
        return self.verdict


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


PASS = LayerVerdict(None, "an image; the picture decides")
UNSURE = LayerVerdict(None, "the probe gives photo 0.800, below 0.9", 0.8, {"photo": 0.8})
SURE = LayerVerdict(Route.PHOTO, "model answers B (photo) at 0.990", 0.99, {"photo": 0.99})


def test_the_first_layer_that_decides_gives_the_route_and_later_layers_are_not_asked() -> None:
    layers = [FakeLayer("structure", PASS), FakeLayer("probe", SURE), FakeLayer("vlm", SURE)]
    router = RouterService(layers, MemoryTrace(), "v1 (fake)")

    routing = router.route("why did this break?", PHOTO, request_id="req-1")

    assert (routing.request_id, routing.route, routing.layer) == ("req-1", Route.PHOTO, "probe")
    assert (routing.confidence, routing.reason) == (0.99, SURE.reason)
    assert routing.probabilities == {"photo": 0.99}
    assert routing.elapsed_ms >= 0
    assert [layer.seen for layer in layers] == [[PHOTO], [PHOTO], []]


def test_every_layer_asked_is_traced_with_what_it_made_of_the_request() -> None:
    trace = MemoryTrace()
    layers = [FakeLayer("structure", PASS), FakeLayer("probe", UNSURE), FakeLayer("vlm", SURE)]

    RouterService(layers, trace, "v1 (fake)").route("why did this break?", PHOTO, "req-2")

    assert [(e.step, e.called, e.error) for e in trace.find("req-2")] == [
        ("route.structure", "router v1 (fake): fake structure", None),
        ("route.probe", "router v1 (fake): fake probe", None),
        ("route.vlm", "router v1 (fake): fake vlm", None),
    ]
    first, second, last = trace.find("req-2")
    assert first.input == {
        "text_chars": 19,
        "attachment": {
            "name": "part.jpg",
            "media_type": "image/jpeg",
            "bytes": 7,
            "sha256": hashlib.sha256(PHOTO.data).hexdigest(),
        },
    }
    assert first.output == {
        "decided": False,
        "route": None,
        "confidence": None,
        "reason": PASS.reason,
        "probabilities": {},
    }
    assert second.output["confidence"] == 0.8
    assert last.output["decided"] is True
    assert last.output["route"] == "photo"


def test_a_text_question_is_traced_without_an_attachment() -> None:
    trace = MemoryTrace()
    text = LayerVerdict(Route.TEXT, "no attachment", 1.0)

    routing = RouterService([FakeLayer("structure", text)], trace, "v1").route("hi", None, "r")

    assert routing.route == Route.TEXT
    assert trace.find("r")[0].input == {"text_chars": 2, "attachment": None}


def test_a_request_no_layer_is_sure_of_fits_no_case() -> None:
    layers = [FakeLayer("structure", PASS), FakeLayer("probe", UNSURE)]

    routing = RouterService(layers, MemoryTrace(), "v1").route(None, PHOTO)

    assert (routing.route, routing.layer, routing.confidence) == (Route.OTHER, "none", None)
    assert routing.reason == f"no layer was sure; the last said: {UNSURE.reason}"
    assert routing.request_id


def test_a_failing_layer_is_traced_with_its_error_and_raised() -> None:
    trace = MemoryTrace()
    layers = [FakeLayer("structure", PASS), FakeLayer("probe", RuntimeError("no GPU"))]

    with pytest.raises(RuntimeError, match="no GPU"):
        RouterService(layers, trace, "v1").route(None, PHOTO, "req-3")

    failed = trace.find("req-3")[-1]
    assert (failed.step, failed.error, failed.output) == (
        "route.probe",
        "RuntimeError: no GPU",
        {"decided": False},
    )


def test_a_trace_that_cannot_be_recorded_does_not_change_the_route(
    caplog: pytest.LogCaptureFixture,
) -> None:
    router = RouterService([FakeLayer("probe", SURE)], MemoryTrace(fail=True), "v1")

    with caplog.at_level(logging.ERROR):
        routing = router.route(None, PHOTO, "req-4")

    assert routing.route == Route.PHOTO
    assert "could not record the trace of request req-4" in caplog.text
