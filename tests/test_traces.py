import pytest

from resourcly.bootstrap import Settings, open_services
from resourcly.errors import NotFound
from tests.conftest import CTC01


def test_a_read_is_recorded_under_its_request_id_and_survives_a_restart(
    settings: Settings,
) -> None:
    with open_services(settings) as services:
        reading = services.drawings.read(CTC01, request_id="req-1")

    with open_services(settings) as services:
        trace = services.traces.lookup("req-1")

    assert reading.request_id == "req-1"
    [event] = trace.events
    assert (event.request_id, event.step, event.error) == ("req-1", "drawings.read", None)
    assert event.called == "reader textlayer-v0 (textlayer)"
    assert event.input == {"drawing": CTC01}
    assert event.output == {"values": 6, "schema_issues": 0}
    assert event.duration_ms >= 0


def test_a_read_without_a_request_id_gets_one(settings: Settings) -> None:
    with open_services(settings) as services:
        reading = services.drawings.read(CTC01)
        trace = services.traces.lookup(reading.request_id)

    assert reading.request_id
    assert [event.step for event in trace.events] == ["drawings.read"]


def test_an_unknown_request_is_not_found(settings: Settings) -> None:
    with open_services(settings) as services, pytest.raises(NotFound, match="no request 'nope'"):
        services.traces.lookup("nope")


def test_a_failed_read_is_recorded_with_its_error(settings: Settings) -> None:
    with open_services(settings) as services:
        with pytest.raises(NotFound):
            services.drawings.read("absent_drawing", request_id="req-2")
        [event] = services.traces.lookup("req-2").events

    assert event.error == "NotFound: no drawing named absent_drawing"
    assert event.output == {"values": 0, "schema_issues": 0}
