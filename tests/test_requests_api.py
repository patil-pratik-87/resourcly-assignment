"""The chat's request endpoints, with the text-layer reader and the stub router."""

import hashlib
import json
import logging
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pymupdf
import pytest
from fastapi.testclient import TestClient

from resourcly.adapters.request_store import JsonRequestStoreAdapter
from resourcly.adapters.text_reader import PyMuPDFTextReaderAdapter
from resourcly.api import create_app
from resourcly.bootstrap import PROJECT_ROOT, READERS, Implementation, Settings
from resourcly.errors import ModelNotCached
from resourcly.models import ReaderOutput, ReadProgress, RequestItem, RequestRecord
from resourcly.ports import Progress
from tests.conftest import CTC01, png

CTC01_PDF = (PROJECT_ROOT / "data" / "drawings" / f"{CTC01}.pdf").read_bytes()
REPORT_PDF = (PROJECT_ROOT / "data" / "reports" / "ntsb_24-013.pdf").read_bytes()


class GatedReader:
    """The text-layer reader, made to report progress, wait at a gate, or fail on demand."""

    gate = threading.Event()
    fail: Exception | None = None

    def __init__(self, folder: Path):
        self.text = PyMuPDFTextReaderAdapter(folder)

    def read(self, drawing: str, progress: Progress | None = None) -> ReaderOutput:
        if progress:
            progress(ReadProgress(page=1, pages=1, done=0, total=1, latest=["title block"]))
        self.gate.wait(timeout=10)
        if self.fail:
            raise self.fail
        return self.text.read(drawing)


@pytest.fixture
def gated(monkeypatch: pytest.MonkeyPatch) -> type[GatedReader]:
    GatedReader.gate, GatedReader.fail = threading.Event(), None
    monkeypatch.setitem(
        READERS,
        "gated",
        Implementation(lambda settings, params: GatedReader(settings.drawings_dir)),
    )
    return GatedReader


@pytest.fixture
def gated_settings(settings: Settings, tmp_path: Path, gated: type) -> Settings:
    versions = tmp_path / "versions"
    (versions / "reader").mkdir(parents=True)
    (versions / "reader" / "gated-v1.toml").write_text('impl = "gated"\n', encoding="utf-8")
    (versions / "router").mkdir()
    stub = PROJECT_ROOT / "versions" / "router" / "stub-v0.toml"
    (versions / "router" / "stub-v0.toml").write_bytes(stub.read_bytes())
    return replace(settings, versions_dir=versions).with_version("reader", "gated-v1")


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as client:
        yield client


@pytest.fixture
def gated_client(gated_settings: Settings, gated: type[GatedReader]) -> Iterator[TestClient]:
    with TestClient(create_app(gated_settings)) as client:
        yield client
        gated.gate.set()


def send(client: TestClient, text: str = "", *files: tuple[str, bytes]) -> dict[str, Any]:
    response = client.post(
        "/api/requests",
        data={"text": text},
        files=[("files", (name, content)) for name, content in files],
    )
    assert response.status_code == 202, response.text
    return response.json()


def wait_for(
    client: TestClient, request_id: str, until: Callable[[dict[str, Any]], bool]
) -> dict[str, Any]:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        record = client.get(f"/api/requests/{request_id}").json()
        if until(record):
            return record
        time.sleep(0.02)
    raise AssertionError(f"request {request_id} never got there: {record}")


def finished(client: TestClient, request_id: str) -> dict[str, Any]:
    return wait_for(client, request_id, lambda record: record["status"] != "working")


def test_a_drawing_is_routed_read_and_its_json_kept(client: TestClient) -> None:
    sent = send(client, "read this", (f"{CTC01}.pdf", CTC01_PDF))

    [item] = sent["items"]
    assert (item["item_id"], item["kind"], item["status"]) == (CTC01, "file", "routing")
    record = finished(client, sent["request_id"])

    [item] = record["items"]
    assert record["status"] == "done"
    assert item["route"]["route"] == "drawing" and item["route"]["layer"] == "stub"
    assert item["route"]["request_id"] == sent["request_id"]
    assert item["route"]["confidence"] == 0.7 and "vector paths" in item["route"]["reason"]
    assert (item["status"], item["issues"], item["pages"]) == ("done", 0, 1)
    result = client.get(f"/api/requests/{sent['request_id']}/items/{CTC01}/result").json()
    assert result["drawing"] == CTC01
    assert len(result["values"]) == item["values"] == 6


def test_the_json_downloads_as_a_file_named_after_the_upload(client: TestClient) -> None:
    sent = send(client, "", ("ctc.pdf", CTC01_PDF))
    finished(client, sent["request_id"])

    response = client.get(f"/api/requests/{sent['request_id']}/items/ctc/result?download=true")

    assert response.headers["content-disposition"] == 'attachment; filename="ctc.json"'
    assert response.json()["drawing"] == "ctc"


def test_a_photo_is_answered_from_the_report_figures_closest_to_it(client: TestClient) -> None:
    sent = send(client, "what is wrong with this bolt?", ("bolt.png", png()))

    [item] = finished(client, sent["request_id"])["items"]

    assert (item["route"]["route"], item["status"]) == ("photo", "answered")
    answer = item["answer"]
    assert (answer["not_in_reports"], answer["matched"]) == (False, True)
    # the model-free versions: the shuffled finder and the closest figures' captions
    best = answer["figures"][0]
    assert answer["answer"].startswith(f"The closest report figure is {best['figure'][:6]} fig")
    citation = answer["findings"][0]["citation"]
    assert citation["figure"] == best["figure"]
    assert item["reply"].startswith(answer["answer"])
    assert item["values"] is None and item["finished_at"]


def test_a_photo_waits_its_turn_then_shows_it_is_being_answered(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate = threading.Event()
    services = client.app.state.services
    answer = services.photo_answers.answer

    def slow(*args: Any) -> Any:
        gate.wait(timeout=10)
        return answer(*args)

    monkeypatch.setattr(services.photo_answers, "answer", slow)
    sent = send(client, "", ("bolt.png", png()))

    record = wait_for(client, sent["request_id"], lambda r: r["items"][0]["status"] == "answering")
    gate.set()

    assert record["status"] == "working" and record["items"][0]["started_at"]
    assert finished(client, sent["request_id"])["items"][0]["status"] == "answered"


def test_a_photo_whose_answer_fails_says_why(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*args: Any) -> Any:
        raise ModelNotCached("org/model is not in the local Hugging Face cache")

    monkeypatch.setattr(client.app.state.services.photo_answers, "answer", broken)
    sent = send(client, "", ("bolt.png", png()))

    [item] = finished(client, sent["request_id"])["items"]

    assert item["status"] == "failed"
    assert item["error"] == "org/model is not in the local Hugging Face cache"


def test_text_alone_is_one_item_routed_and_answered(client: TestClient) -> None:
    sent = send(client, "why did the bracket crack?")

    [item] = finished(client, sent["request_id"])["items"]

    assert (item["item_id"], item["kind"], item["name"]) == (
        "message",
        "text",
        "why did the bracket crack?",
    )
    assert (item["route"]["route"], item["status"]) == ("text", "answered")
    assert "not available yet" in item["reply"]


def test_a_file_that_fits_no_case_says_so(client: TestClient) -> None:
    sent = send(client, "", ("report.pdf", REPORT_PDF))

    [item] = finished(client, sent["request_id"])["items"]

    assert (item["route"]["route"], item["status"]) == ("other", "answered")
    assert "neither case" in item["reply"]


def test_many_files_in_one_message_are_one_request(client: TestClient) -> None:
    sent = send(
        client,
        "",
        ("a.pdf", CTC01_PDF),
        ("b.pdf", CTC01_PDF),
        ("report.pdf", REPORT_PDF),
        ("crack.png", png()),
    )

    record = finished(client, sent["request_id"])

    routes = {item["item_id"]: (item["route"]["route"], item["status"]) for item in record["items"]}
    assert routes == {
        "a": ("drawing", "done"),
        "b": ("drawing", "done"),
        "report": ("other", "answered"),
        "crack": ("photo", "answered"),
    }
    [listed] = client.get("/api/requests").json()
    assert listed["request_id"] == sent["request_id"] and len(listed["items"]) == 4


def test_a_file_the_agent_cannot_take_fails_alone(client: TestClient) -> None:
    sent = send(client, "", ("notes.txt", b"plain text"), ("ctc.pdf", CTC01_PDF))

    record = finished(client, sent["request_id"])

    rejected, drawing = record["items"]
    assert (rejected["name"], rejected["status"], rejected["route"]) == (
        "notes.txt",
        "failed",
        None,
    )
    assert rejected["error"] == "notes.txt is not a PDF, PNG, JPEG or TIFF file"
    assert drawing["status"] == "done"
    assert record["status"] == "failed"


def test_an_empty_message_is_refused(client: TestClient) -> None:
    response = client.post("/api/requests", data={"text": "  "})

    assert response.status_code == 422
    assert response.json()["detail"] == "Send some text, a file, or both."
    assert client.get("/api/requests").json() == []


def test_a_read_shows_live_progress_while_it_runs(
    gated_client: TestClient, gated: type[GatedReader]
) -> None:
    sent = send(gated_client, "", ("ctc.pdf", CTC01_PDF))

    record = wait_for(
        gated_client, sent["request_id"], lambda record: record["items"][0]["progress"]
    )

    [item] = record["items"]
    assert item["status"] == "reading" and record["status"] == "working"
    assert item["started_at"] is not None
    assert item["progress"]["latest"] == ["title block"]
    gated.gate.set()
    [item] = finished(gated_client, sent["request_id"])["items"]
    assert (item["status"], item["progress"]) == ("done", None)


def test_each_step_is_traced_as_it_happens_not_when_the_request_ends(
    gated_client: TestClient, gated: type[GatedReader]
) -> None:
    sent = send(gated_client, "", ("ctc.pdf", CTC01_PDF))
    wait_for(gated_client, sent["request_id"], lambda record: record["items"][0]["progress"])
    trace = gated_client.get(f"/api/requests/{sent['request_id']}/trace").json()

    steps = [event["step"] for event in trace["events"]]

    assert gated_client.get(f"/api/requests/{sent['request_id']}").json()["status"] == "working"
    assert steps == ["requests.receive", "uploads.save", "route.stub", "router.route"]
    gated.gate.set()
    finished(gated_client, sent["request_id"])


def test_a_failed_read_keeps_its_error(gated_client: TestClient, gated: type[GatedReader]) -> None:
    gated.fail = RuntimeError("the model ran out of memory")
    gated.gate.set()
    sent = send(gated_client, "", ("ctc.pdf", CTC01_PDF))

    [item] = finished(gated_client, sent["request_id"])["items"]

    assert (item["status"], item["error"]) == ("failed", "the model ran out of memory")
    response = gated_client.get(f"/api/requests/{sent['request_id']}/items/ctc/result")
    assert response.status_code == 404


def test_a_missing_model_fails_the_read_with_one_log_line_and_no_traceback(
    gated_client: TestClient, gated: type[GatedReader], caplog: pytest.LogCaptureFixture
) -> None:
    gated.fail = ModelNotCached("org/model is not in the local Hugging Face cache")
    gated.gate.set()

    with caplog.at_level(logging.WARNING, logger="resourcly.agent"):
        sent = send(gated_client, "", ("ctc.pdf", CTC01_PDF))
        [item] = finished(gated_client, sent["request_id"])["items"]

    assert (item["status"], item["error"]) == (
        "failed",
        "org/model is not in the local Hugging Face cache",
    )
    logged = [record for record in caplog.records if record.name == "resourcly.agent"]
    assert [record.exc_info for record in logged] == [None]


def test_every_step_is_traced_under_the_request_id(client: TestClient) -> None:
    sent = send(client, "two things", ("ctc.pdf", CTC01_PDF), ("crack.png", png()))
    finished(client, sent["request_id"])

    trace = client.get(f"/api/requests/{sent['request_id']}/trace").json()

    steps = [(event["step"], event["input"].get("item")) for event in trace["events"]]
    # The router traces each layer it asks, then the agent traces the item's routing.
    assert steps == [
        ("requests.receive", None),
        ("uploads.save", "ctc"),
        ("uploads.save", "crack"),
        ("route.stub", None),
        ("router.route", "ctc"),
        ("route.stub", None),
        ("router.route", "crack"),
        ("drawings.read", None),
        ("failure.find", None),
        ("answer.photo", None),
    ]
    events = {event["step"]: event for event in trace["events"]}
    assert events["router.route"]["called"] == "router stub-v0 (stub)"
    assert events["drawings.read"]["called"] == "reader textlayer-v0 (textlayer)"
    assert events["drawings.read"]["input"] == {"drawing": "ctc"}
    assert events["failure.find"]["called"] == "finder shuffled-v0 (shuffled)"
    assert events["answer.photo"]["called"] == (
        "answer captions-v0 (captions): no model: the closest figures' captions"
    )
    assert events["answer.photo"]["input"]["question_chars"] == 10
    assert events["requests.receive"]["input"] == {
        "text_chars": 10,
        "text_sha256": hashlib.sha256(b"two things").hexdigest(),
        "files": ["ctc.pdf", "crack.png"],
    }


def test_the_text_is_kept_with_the_request_but_traced_only_by_length_and_hash(
    client: TestClient,
) -> None:
    secret = "my part number is X-7731, mail me at someone@example.com"
    sent = send(client, secret, ("ctc.pdf", CTC01_PDF))
    finished(client, sent["request_id"])

    trace = client.get(f"/api/requests/{sent['request_id']}/trace").json()

    assert client.get(f"/api/requests/{sent['request_id']}").json()["text"] == secret
    assert "X-7731" not in json.dumps(trace)
    routed = next(event for event in trace["events"] if event["step"] == "router.route")
    assert routed["input"]["text_chars"] == len(secret)
    assert "text" not in routed["input"]


def test_a_file_over_the_size_cap_is_refused_whole(settings: Settings) -> None:
    capped = replace(settings, max_upload_bytes=52_429)  # 0.05 MB; CTC-01 is 55 KB
    with TestClient(create_app(capped)) as client:
        response = client.post(
            "/api/requests",
            data={"text": "read"},
            files=[("files", ("small.png", png())), ("files", ("ctc.pdf", CTC01_PDF))],
        )
        listed = client.get("/api/requests").json()

    assert response.status_code == 413
    assert response.json()["detail"] == "ctc.pdf is 0.1 MB; each file can be at most 0.05 MB."
    assert listed == []


def test_a_message_over_the_file_count_cap_is_refused(settings: Settings) -> None:
    capped = replace(settings, max_files=2)
    with TestClient(create_app(capped)) as client:
        response = client.post(
            "/api/requests", files=[("files", (f"{n}.png", png())) for n in range(3)]
        )

    assert response.status_code == 413
    assert response.json()["detail"] == "A message can carry at most 2 files; this one has 3."


def test_an_unknown_request_or_result_is_not_found(client: TestClient) -> None:
    sent = send(client, "hello")
    finished(client, sent["request_id"])

    assert client.get("/api/requests/absent").status_code == 404
    assert client.get("/api/requests/absent/trace").status_code == 404
    assert client.get(f"/api/requests/{sent['request_id']}/items/message/result").status_code == (
        404
    )


def test_each_page_of_an_upload_renders_as_an_image(client: TestClient) -> None:
    sent = send(client, "", (f"{CTC01}.pdf", CTC01_PDF), ("bolt.png", png(40, 30)))
    finished(client, sent["request_id"])
    items = f"/api/requests/{sent['request_id']}/items"

    drawing = client.get(f"{items}/{CTC01}/pages/1.png")
    small = client.get(f"{items}/{CTC01}/pages/1.png?dpi=72")
    photo = client.get(f"{items}/bolt/pages/1.png")

    assert drawing.status_code == 200 and drawing.headers["content-type"] == "image/png"
    page = pymupdf.Pixmap(drawing.content)
    assert pymupdf.Pixmap(small.content).width * 150 // 72 in range(page.width - 2, page.width + 3)
    # A photo is kept as a one-page PDF too, so it renders the same way, its shape unchanged.
    picture = pymupdf.Pixmap(photo.content)
    assert photo.status_code == 200 and abs(picture.width / picture.height - 40 / 30) < 0.03


@pytest.mark.parametrize(
    ("path", "status"),
    [
        (f"{CTC01}/pages/2.png", 404),
        ("absent/pages/1.png", 404),
        ("message/pages/1.png", 404),
        (f"{CTC01}/pages/1.png?dpi=10", 422),
    ],
)
def test_a_page_that_is_not_there_is_not_found(client: TestClient, path: str, status: int) -> None:
    sent = send(client, "read this", (f"{CTC01}.pdf", CTC01_PDF))
    text = send(client, "hello")
    finished(client, sent["request_id"])
    finished(client, text["request_id"])
    request_id = text["request_id"] if path.startswith("message") else sent["request_id"]

    assert client.get(f"/api/requests/{request_id}/items/{path}").status_code == status
    assert client.get(f"/api/requests/absent/items/{CTC01}/pages/1.png").status_code == 404


def test_requests_list_newest_first_up_to_the_limit(client: TestClient) -> None:
    ids = []
    for n in range(3):
        ids.append(send(client, f"message {n}")["request_id"])
        time.sleep(0.005)  # created_at has millisecond precision

    listed = client.get("/api/requests?limit=2").json()

    assert [record["request_id"] for record in listed] == ids[:0:-1]


def test_the_agent_names_its_versions_and_its_upload_caps(client: TestClient) -> None:
    assert client.get("/api/agent").json() == {
        "reader": "textlayer-v0 (textlayer)",
        "router": "stub-v0 (stub)",
        "failure": "shuffled-v0 (shuffled)",
        "answer": "captions-v0 (captions)",
        "max_file_mb": 50,
        "max_files": 50,
    }


def test_work_cut_off_by_a_restart_is_marked_failed(settings: Settings) -> None:
    JsonRequestStoreAdapter(settings.uploads_dir).save(
        RequestRecord(
            request_id="r1",
            text="",
            created_at="2026-11-01T10:00:00.000+00:00",
            items=[RequestItem(item_id="ctc", kind="file", name="ctc.pdf", status="reading")],
        )
    )

    with TestClient(create_app(settings)) as client:
        [item] = client.get("/api/requests/r1").json()["items"]

    assert item["status"] == "failed"
    assert item["error"] == "The server stopped before this finished. Send the file again."
