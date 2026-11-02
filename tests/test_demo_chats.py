"""The demo chats: a drawing and a photo request, answered before, that the chat opens with.

They are stored in demo/ in the request store's own layout, with their traces, and loaded on
serve with no model. See demo/README.md for where each output comes from.
"""

import json
import shutil
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pymupdf
import pytest
from fastapi.testclient import TestClient

from resourcly.api import create_app
from resourcly.bootstrap import PROJECT_ROOT, Settings
from resourcly.models import RequestRecord, TraceEvent

DEMO = PROJECT_ROOT / "demo"
DEMO_IDS = sorted(path.parent.name for path in DEMO.glob("*/request.json"))
PHOTO_RUNS = PROJECT_ROOT / "evals" / "photo-answers" / "runs" / "photo-v2-spot.jsonl"


def demo_record(route: str) -> RequestRecord:
    for request_id in DEMO_IDS:
        record = RequestRecord.model_validate_json(
            (DEMO / request_id / "request.json").read_text(encoding="utf-8")
        )
        if record.items[0].route and record.items[0].route.route == route:
            return record
    raise AssertionError(f"no {route} demo")


def demo_trace(request_id: str) -> list[TraceEvent]:
    events = json.loads((DEMO / request_id / "trace.json").read_text(encoding="utf-8"))
    return [TraceEvent.model_validate(event) for event in events]


@pytest.fixture
def demo_settings(settings: Settings) -> Settings:
    return replace(settings, demo_dir=DEMO)


@pytest.fixture
def client(demo_settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(demo_settings)) as client:
        yield client


def test_there_is_one_drawing_demo_and_one_photo_demo() -> None:
    assert len(DEMO_IDS) == 2
    assert demo_record("drawing").items[0].name == "nist_ctc_01_asme1_rd.pdf"
    assert demo_record("photo").items[0].name == "pos_18-061_fig05_v1.jpg"


@pytest.mark.parametrize("route", ["drawing", "photo"])
def test_each_demo_is_a_finished_request_marked_demo_with_its_trace(route: str) -> None:
    record = demo_record(route)

    assert record.demo is True
    assert record.status == "done"
    assert len(record.items) == 1
    events = demo_trace(record.request_id)
    assert {event.request_id for event in events} == {record.request_id}
    assert [event.step for event in events][:3] == [
        "requests.receive",
        "uploads.save",
        "route.structure",
    ]


def test_the_drawing_demo_is_the_vector_crop_v2_reading_in_outputs() -> None:
    record = demo_record("drawing")
    item = record.items[0]
    stored = json.loads((PROJECT_ROOT / "outputs" / "nist_ctc_01_asme1_rd.json").read_text())
    result = DEMO / record.request_id / "results" / f"{item.item_id}.json"

    assert json.loads(result.read_text(encoding="utf-8")) == stored
    assert item.values == len(stored["values"])
    read = demo_trace(record.request_id)[-1]
    assert (read.step, read.called) == ("drawings.read", "reader vector-crop-v2 (vector-crop)")


def test_the_photo_demo_is_the_stored_photo_v2_answer() -> None:
    record = demo_record("photo")
    item = record.items[0]
    stored = next(
        json.loads(line)
        for line in PHOTO_RUNS.read_text(encoding="utf-8").splitlines()
        if json.loads(line)["case_id"] == "pos_18-061_fig05_v1"
    )

    assert item.answer is not None
    assert item.answer.model_dump(mode="json") == stored["answer"]
    answer = demo_trace(record.request_id)[-1]
    assert answer.step == "answer.photo"
    assert answer.called.startswith("answer photo-v2 (vlm): ")
    assert answer.output["text"] == stored["model_text"]


def test_serve_opens_the_chat_with_the_demos(client: TestClient) -> None:
    records = client.get("/api/requests").json()

    assert sorted(record["request_id"] for record in records) == DEMO_IDS
    assert all(record["demo"] for record in records)


def test_a_request_sent_after_the_demos_is_not_a_demo_and_comes_first(client: TestClient) -> None:
    sent = client.post("/api/requests", data={"text": "hello"}).json()

    records = client.get("/api/requests").json()
    assert records[0]["request_id"] == sent["request_id"]
    assert records[0]["demo"] is False


def test_the_demo_drawing_shows_its_result_page_and_trace_with_no_model(
    client: TestClient,
) -> None:
    record = demo_record("drawing")
    item = record.items[0].item_id
    base = f"/api/requests/{record.request_id}"

    result = client.get(f"{base}/items/{item}/result")
    page = client.get(f"{base}/items/{item}/pages/1.png")
    trace = client.get(f"{base}/trace")

    assert len(result.json()["values"]) == record.items[0].values
    assert page.headers["content-type"] == "image/png"
    assert pymupdf.Pixmap(page.content).width > 0
    assert [event["step"] for event in trace.json()["events"]][-1] == "drawings.read"


def test_the_demo_photo_shows_its_photo_cited_figures_and_trace_with_no_model(
    client: TestClient,
) -> None:
    record = demo_record("photo")
    item = record.items[0]
    base = f"/api/requests/{record.request_id}"

    photo = client.get(f"{base}/items/{item.item_id}/pages/1.png")
    trace = client.get(f"{base}/trace").json()["events"]

    assert photo.headers["content-type"] == "image/png"
    assert item.answer is not None
    for figure in item.answer.figures:
        report, number = figure.figure.split("/fig")
        image = client.get(f"/api/reports/{report}/figures/{int(number)}.png?max_side=200")
        assert image.headers["content-type"] == "image/png", figure.figure
    steps = [event["step"] for event in trace]
    assert steps[-2:] == ["failure.find", "answer.photo"]


def test_demos_never_overwrite_a_request_already_in_the_store(demo_settings: Settings) -> None:
    record = demo_record("drawing")
    folder = demo_settings.uploads_dir / record.request_id
    folder.mkdir(parents=True)
    mine = record.model_copy(update={"text": "mine", "demo": False})
    (folder / "request.json").write_text(mine.model_dump_json(), encoding="utf-8")

    with TestClient(create_app(demo_settings)) as client:
        kept = client.get(f"/api/requests/{record.request_id}").json()

    assert (kept["text"], kept["demo"]) == ("mine", False)


def test_serving_again_keeps_one_copy_of_each_demo_and_its_trace(demo_settings: Settings) -> None:
    for _ in range(2):
        with TestClient(create_app(demo_settings)) as client:
            records = client.get("/api/requests").json()
            traces = {
                request_id: client.get(f"/api/requests/{request_id}/trace").json()["events"]
                for request_id in DEMO_IDS
            }

    assert sorted(record["request_id"] for record in records) == DEMO_IDS
    for request_id, events in traces.items():
        assert len(events) == len(demo_trace(request_id))


def test_a_demo_whose_files_are_gone_is_loaded_again(demo_settings: Settings) -> None:
    with TestClient(create_app(demo_settings)):
        pass
    shutil.rmtree(demo_settings.uploads_dir / DEMO_IDS[0])

    with TestClient(create_app(demo_settings)) as client:
        records = client.get("/api/requests").json()

    assert sorted(record["request_id"] for record in records) == DEMO_IDS


def test_without_a_demo_folder_the_chat_opens_empty(settings: Settings) -> None:
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/requests").json() == []


def test_the_demos_are_on_by_default_and_the_environment_turns_them_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert Settings().demo_dir == DEMO
    assert Settings.from_env().demo_dir == DEMO

    monkeypatch.setenv("RESOURCLY_DEMO_CHATS", "0")

    assert Settings.from_env().demo_dir is None


def test_a_demo_folder_with_a_broken_request_is_skipped(
    demo_settings: Settings, tmp_path: Path
) -> None:
    demos = tmp_path / "demo"
    shutil.copytree(DEMO, demos)
    (demos / DEMO_IDS[0] / "request.json").write_text("{", encoding="utf-8")

    with TestClient(create_app(replace(demo_settings, demo_dir=demos))) as client:
        records = client.get("/api/requests").json()

    assert [record["request_id"] for record in records] == DEMO_IDS[1:]
