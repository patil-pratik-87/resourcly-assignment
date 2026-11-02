import sqlite3

import pytest

from resourcly.bootstrap import Settings, open_services
from resourcly.errors import NotFound
from resourcly.models import Issue, ReaderOutput, TraceEvent
from resourcly.services import DrawingService
from tests.conftest import CTC01


def test_reads_a_drawing_through_the_services(settings: Settings) -> None:
    with open_services(settings) as services:
        reading = services.drawings.read(CTC01)

    assert reading.drawing == CTC01
    assert reading.issues == []
    assert len(reading.document["values"]) == 6
    # no reader measures how sure it is, so it says nothing rather than a made-up number
    assert {value["confidence"] for value in reading.document["values"]} == {None}


class BrokenTrace:
    def record(self, event: TraceEvent) -> None:
        raise sqlite3.OperationalError("database is locked")

    def find(self, request_id: str) -> list[TraceEvent]:
        return []


class FixedReader:
    def __init__(self, error: Exception | None = None):
        self.error = error

    def read(self, drawing: str, progress=None) -> ReaderOutput:
        if self.error:
            raise self.error
        return ReaderOutput(
            document={"drawing": drawing, "page_count": 1, "title_block": {}, "values": []}
        )


def test_a_trace_failure_does_not_lose_the_reading(caplog: pytest.LogCaptureFixture) -> None:
    service = DrawingService(reader=FixedReader(), trace=BrokenTrace(), reader_name="fixed")

    reading = service.read(CTC01, request_id="r1")

    assert reading.document["values"] == []
    assert "could not record the trace of request r1" in caplog.text
    assert "database is locked" in caplog.text


def test_a_trace_failure_does_not_hide_the_reader_error() -> None:
    reader = FixedReader(error=NotFound("no drawing named absent"))
    service = DrawingService(reader=reader, trace=BrokenTrace(), reader_name="fixed")

    with pytest.raises(NotFound, match="no drawing named absent"):
        service.read("absent", request_id="r2")


class KeptTrace:
    def __init__(self):
        self.events: list[TraceEvent] = []

    def record(self, event: TraceEvent) -> None:
        self.events.append(event)

    def find(self, request_id: str) -> list[TraceEvent]:
        return self.events


class AnswerIssueReader:
    def read(self, drawing: str, progress=None) -> ReaderOutput:
        document = {"drawing": drawing, "page_count": 1, "title_block": {}, "values": []}
        issue = Issue(loc=["answers", "page", 1, "callout", 2], message="the crop answer: x")
        return ReaderOutput(document=document, answer_issues=[issue])


def test_an_answer_the_reader_could_not_use_is_an_issue_of_the_reading_and_counted() -> None:
    trace = KeptTrace()
    service = DrawingService(reader=AnswerIssueReader(), trace=trace, reader_name="fixed")

    reading = service.read(CTC01, request_id="r3")

    assert [(i.loc, i.message) for i in reading.issues] == [
        (["answers", "page", 1, "callout", 2], "the crop answer: x")
    ]
    [event] = trace.events
    assert event.output == {"values": 0, "schema_issues": 0, "answer_issues": 1}
