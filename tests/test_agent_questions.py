"""Questions sent with files or alone: each is answered on the card it is about, from records."""

import json
import threading
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pymupdf
import pytest
from fastapi.testclient import TestClient

from resourcly.adapters.rules_answer import RulesAnswerAdapter
from resourcly.api import create_app
from resourcly.bootstrap import (
    PROJECT_ROOT,
    QUESTIONERS,
    READERS,
    ROUTERS,
    Implementation,
    Settings,
)
from resourcly.models import LayerVerdict, ReaderOutput, Route, Selection
from resourcly.ports import Progress
from tests.conftest import CTC01, png
from tests.test_requests_api import CTC01_PDF, finished, send, wait_for

OUTPUT = json.loads((PROJECT_ROOT / "outputs" / f"{CTC01}.json").read_text(encoding="utf-8"))


class OutputsReader:
    """Reads any drawing as the reader's JSON of CTC-01 in outputs/; reads of `slow` wait."""

    gate = threading.Event()
    reads: list[str] = []

    def __init__(self, folder: Path):
        self.folder = folder

    def read(self, drawing: str, progress: Progress | None = None) -> ReaderOutput:
        self.reads.append(drawing)
        if drawing.startswith("slow"):
            self.gate.wait(timeout=10)
        if drawing.startswith("picture"):
            # read from the whole page, as vector-crop-v2 reads a page with no vector callouts
            whole = [{**v, "bbox": [0.0, 0.0, 1.0, 1.0]} for v in OUTPUT["values"]]
            return ReaderOutput(document={**OUTPUT, "drawing": drawing, "values": whole})
        return ReaderOutput(document={**OUTPUT, "drawing": drawing})


class BlockingAnswerer(RulesAnswerAdapter):
    """The rules answerer, whose select waits until the test lets it go."""

    release = threading.Event()

    def select(self, evidence: Any) -> Selection:
        self.release.wait(timeout=10)
        return super().select(evidence)


class DrawingLayer:
    """Routes every file as a drawing, as the router may route a picture of one."""

    name = "drawing"
    called = "fake layer: every file is a drawing"

    def decide(self, attachment: Any) -> LayerVerdict:
        if attachment is None:
            return LayerVerdict(Route.TEXT, "no attachment", 1.0)
        return LayerVerdict(Route.DRAWING, "every file is a drawing", 0.9)


@pytest.fixture
def asking(settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    OutputsReader.gate, OutputsReader.reads = threading.Event(), []
    BlockingAnswerer.release = threading.Event()
    monkeypatch.setitem(
        READERS, "outputs", Implementation(lambda settings, params: OutputsReader(settings))
    )
    monkeypatch.setitem(
        QUESTIONERS, "blocking", Implementation(lambda settings, params: BlockingAnswerer())
    )
    monkeypatch.setitem(
        ROUTERS, "drawings", Implementation(lambda settings, params: [DrawingLayer()])
    )
    versions = tmp_path / "versions"
    for component in ("reader", "router", "qa", "failure", "answer"):
        (versions / component).mkdir(parents=True)
    (versions / "reader" / "outputs-v1.toml").write_text('impl = "outputs"\n', encoding="utf-8")
    index = PROJECT_ROOT / "versions" / "failure" / "indexes" / "dinov2-base-v1.json"
    (versions / "answer" / "captions-v0.toml").write_text(
        f'impl = "captions"\nindex = "{index}"\n', encoding="utf-8"
    )
    for component, name in (("router", "stub-v0"), ("qa", "rules-v0"), ("failure", "shuffled-v0")):
        source = PROJECT_ROOT / "versions" / component / f"{name}.toml"
        (versions / component / f"{name}.toml").write_bytes(source.read_bytes())
    (versions / "qa" / "blocking-v1.toml").write_text('impl = "blocking"\n', encoding="utf-8")
    (versions / "router" / "drawings-v1.toml").write_text('impl = "drawings"\n', encoding="utf-8")
    return replace(settings, versions_dir=versions).with_version("reader", "outputs-v1")


@pytest.fixture
def client(asking: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(asking)) as client:
        yield client
        OutputsReader.gate.set()
        BlockingAnswerer.release.set()


def steps(client: TestClient, request_id: str) -> list[str]:
    return [e["step"] for e in client.get(f"/api/requests/{request_id}/trace").json()["events"]]


def test_a_question_with_a_drawing_puts_a_checked_reply_on_its_card(client: TestClient) -> None:
    sent = send(client, "What angle is dimensioned on this part?", ("ctc.pdf", CTC01_PDF))

    record = finished(client, sent["request_id"])

    [item] = record["items"]
    assert (item["status"], item["values"]) == ("done", 23)
    assert item["qa"]["outcome"] == "answer"
    assert item["qa"]["checked"] is True
    [cited] = item["qa"]["citations"]
    assert (cited["ref"], cited["item_id"], cited["request_id"]) == (
        "ctc01-13",
        "ctc",
        sent["request_id"],
    )
    assert item["reply"].startswith("60° ±0.5° (ctc01-13, page 1).")
    order = ["answer.gate", "drawings.read", "answer.select", "answer.check"]
    assert [step for step in steps(client, sent["request_id"]) if step in order] == order


def test_a_message_that_only_asks_for_the_read_gets_no_answer(client: TestClient) -> None:
    sent = send(client, "read this", ("ctc.pdf", CTC01_PDF))

    [item] = finished(client, sent["request_id"])["items"]

    assert (item["status"], item["qa"], item["reply"]) == ("done", None, None)
    assert "answer.select" not in steps(client, sent["request_id"])
    assert "answer.gate" in steps(client, sent["request_id"])


def test_a_drawing_shows_it_is_being_answered_after_its_read(
    asking: Settings,
) -> None:
    with TestClient(create_app(asking.with_version("qa", "blocking-v1"))) as client:
        sent = send(client, "Is it flat?", ("ctc.pdf", CTC01_PDF))

        record = wait_for(
            client, sent["request_id"], lambda r: r["items"][0]["status"] == "answering"
        )
        BlockingAnswerer.release.set()

        assert record["status"] == "working" and record["items"][0]["values"] == 23
        assert finished(client, sent["request_id"])["items"][0]["status"] == "done"


def test_an_answer_runs_on_its_own_lane_so_reads_go_on_while_it_waits(
    asking: Settings,
) -> None:
    with TestClient(create_app(asking.with_version("qa", "blocking-v1"))) as client:
        asked = send(client, "Is it flat?", ("ctc.pdf", CTC01_PDF))
        wait_for(client, asked["request_id"], lambda r: r["items"][0]["status"] == "answering")

        read = finished(client, send(client, "", ("other.pdf", CTC01_PDF))["request_id"])

        assert read["items"][0]["status"] == "done"
        assert client.get(f"/api/requests/{asked['request_id']}").json()["status"] == "working"
        BlockingAnswerer.release.set()
        assert finished(client, asked["request_id"])["items"][0]["qa"]["outcome"] == "candidates"


def test_a_value_crops_from_its_page_with_a_margin(client: TestClient) -> None:
    sent = send(client, "", ("ctc.pdf", CTC01_PDF))
    finished(client, sent["request_id"])
    crops = f"/api/requests/{sent['request_id']}/items/ctc/crops"
    [x0, y0, x1, y1] = next(v for v in OUTPUT["values"] if v["id"] == "ctc01-13")["bbox"]

    crop = client.get(f"{crops}/ctc01-13.png")

    assert crop.status_code == 200 and crop.headers["content-type"] == "image/png"
    image = pymupdf.Pixmap(crop.content)
    page = pymupdf.open(stream=CTC01_PDF)[0].rect
    # 300 dpi, with 6 points of margin on each side
    expected = ((x1 - x0) * page.width + 12) * 300 / 72
    assert abs(image.width - expected) < 4
    assert client.get(f"{crops}/ctc01-99.png").status_code == 404


def ask(client: TestClient, text: str, conversation_id: str, *about: str) -> dict[str, Any]:
    response = client.post(
        "/api/requests",
        data={"text": text, "conversation_id": conversation_id, "about": list(about)},
    )
    assert response.status_code == 202, response.text
    return response.json()


def test_the_server_starts_a_conversation_and_a_reply_joins_it(client: TestClient) -> None:
    first = send(client, "read this", ("ctc.pdf", CTC01_PDF))

    second = ask(client, "and the flatness?", first["conversation_id"])

    assert len(first["conversation_id"]) == 32
    assert second["conversation_id"] == first["conversation_id"]
    assert send(client, "hi")["conversation_id"] != first["conversation_id"]


def test_a_follow_up_about_a_drawing_reuses_its_json_and_reads_nothing(
    client: TestClient,
) -> None:
    first = send(client, "read this", ("ctc.pdf", CTC01_PDF))
    finished(client, first["request_id"])
    reads = len(OutputsReader.reads)

    follow = ask(
        client, "What angle is dimensioned?", first["conversation_id"], f"{first['request_id']}/ctc"
    )
    [message] = finished(client, follow["request_id"])["items"]

    assert (message["item_id"], message["status"]) == ("message", "answered")
    [cited] = message["qa"]["citations"]
    assert (cited["ref"], cited["request_id"], cited["item_id"]) == (
        "ctc01-13",
        first["request_id"],
        "ctc",
    )
    assert len(OutputsReader.reads) == reads
    assert "drawings.read" not in steps(client, follow["request_id"])
    assert "answer.select" in steps(client, follow["request_id"])


def test_a_picked_value_is_the_answer_with_no_model_call(client: TestClient) -> None:
    first = send(client, "Is it flat?", ("ctc.pdf", CTC01_PDF))
    [drawing] = finished(client, first["request_id"])["items"]
    assert drawing["qa"]["outcome"] == "candidates"

    picked = f"{first['request_id']}/ctc/{drawing['qa']['candidates'][1]['ref']}"
    follow = ask(client, "Is it flat?", first["conversation_id"], picked)
    [message] = finished(client, follow["request_id"])["items"]

    assert message["qa"]["outcome"] == "answer"
    assert message["qa"]["citations"][0]["ref"] == "ctc01-12"
    assert message["reply"].startswith("▱ 1.5 (ctc01-12, page 1).")
    assert "answer.select" not in steps(client, follow["request_id"])
    assert "answer.check" in steps(client, follow["request_id"])


def test_a_follow_up_about_a_photo_reuses_its_matches(client: TestClient) -> None:
    first = send(client, "", ("bolt.png", png()))
    [photo] = finished(client, first["request_id"])["items"]

    follow = ask(
        client, "What should I check?", first["conversation_id"], f"{first['request_id']}/bolt"
    )
    [message] = finished(client, follow["request_id"])["items"]

    assert message["answer"]["figures"] == photo["answer"]["figures"]
    assert "failure.find" not in steps(client, follow["request_id"])
    assert "answer.photo" in steps(client, follow["request_id"])


def test_the_last_turns_of_the_conversation_go_into_the_prompt(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str] = []
    questions = client.app.state.services.questions
    select = questions.answerer.select
    monkeypatch.setattr(
        questions.answerer,
        "select",
        lambda evidence: seen.append(evidence.blocks) or select(evidence),
    )
    first = send(client, "Is it flat?", ("ctc.pdf", CTC01_PDF))
    finished(client, first["request_id"])

    follow = ask(client, "And the angle?", first["conversation_id"], f"{first['request_id']}/ctc")
    finished(client, follow["request_id"])

    assert "<earlier_turns>\n(none)\n</earlier_turns>" in seen[0]
    assert "User: Is it flat?\nAgent: 2 values on the drawing could be the flatness." in seen[1]


def test_a_message_about_something_that_is_not_there_is_refused(client: TestClient) -> None:
    response = client.post("/api/requests", data={"text": "and this?", "about": ["nope/ctc"]})

    assert response.status_code == 422
    assert "something earlier that is gone" in response.json()["detail"]


def test_text_alone_gets_an_answer_whose_statements_cite_report_pages(client: TestClient) -> None:
    sent = send(client, "What throttle position was measured on the accident control?")

    [message] = finished(client, sent["request_id"])["items"]

    qa = message["qa"]
    assert (message["status"], qa["route"], qa["outcome"]) == ("answered", "text", "answer")
    [cited] = qa["citations"]
    assert (cited["kind"], cited["ref"], cited["page"]) == ("passage", "16-006 p2", 2)
    assert cited["quote"].startswith("The ")
    assert message["reply"].endswith("[16-006 p2]")
    assert steps(client, sent["request_id"])[-2:] == ["answer.write", "answer.check"]


def test_read_these_with_many_files_makes_no_answer_call(client: TestClient) -> None:
    sent = send(client, "read these", ("a.pdf", CTC01_PDF), ("b.pdf", CTC01_PDF), ("c.png", png()))

    record = finished(client, sent["request_id"])

    assert [item["item_id"] for item in record["items"]] == ["a", "b", "c"]
    assert all(item["qa"] is None for item in record["items"])
    trace = steps(client, sent["request_id"])
    assert trace.count("answer.gate") == 1
    assert "answer.select" not in trace and "answer.write" not in trace
    photo = next(
        e
        for e in client.get(f"/api/requests/{sent['request_id']}/trace").json()["events"]
        if e["step"] == "answer.photo"
    )
    assert photo["input"]["question"] == "default"


def test_a_question_over_many_drawings_is_one_answer_on_the_message_card(
    client: TestClient,
) -> None:
    sent = send(client, "What angle is dimensioned?", ("a.pdf", CTC01_PDF), ("b.pdf", CTC01_PDF))

    record = finished(client, sent["request_id"])

    [a, b, message] = record["items"]
    assert (a["status"], a["qa"], b["status"], b["qa"]) == ("done", None, "done", None)
    assert (message["item_id"], message["kind"], message["status"]) == (
        "message",
        "text",
        "answered",
    )
    assert (message["route"]["route"], message["route"]["layer"]) == ("text", "gate")
    qa = message["qa"]
    assert qa["outcome"] == "candidates"
    assert [(c["item_id"], c["ref"]) for c in qa["candidates"]] == [
        ("a", "ctc01-13"),
        ("b", "ctc01-13"),
    ]
    assert steps(client, sent["request_id"]).count("answer.select") == 1


def test_a_question_beside_a_file_that_fits_no_case_is_answered_from_the_reports(
    client: TestClient,
) -> None:
    report = (PROJECT_ROOT / "data" / "reports" / "ntsb_24-013.pdf").read_bytes()
    sent = send(client, "What caused the throttle arm to fracture?", ("report.pdf", report))

    [file, message] = finished(client, sent["request_id"])["items"]

    assert (file["route"]["route"], file["status"]) == ("other", "answered")
    assert (message["qa"]["route"], message["status"]) == ("text", "answered")
    assert message["qa"]["citations"][0]["ref"].startswith("24-013")


def test_a_picture_routed_as_a_drawing_answers_from_values_read_from_a_picture(
    asking: Settings,
) -> None:
    with TestClient(create_app(asking.with_version("router", "drawings-v1"))) as client:
        sent = send(client, "What angle is dimensioned?", ("picture.png", png()))
        [item] = finished(client, sent["request_id"])["items"]
        crop = client.get(f"/api/requests/{sent['request_id']}/items/picture/crops/ctc01-13.png")

    assert item["route"]["route"] == "drawing"
    assert (item["qa"]["outcome"], item["qa"]["picture"]) == ("answer", True)
    assert item["qa"]["citations"][0]["bbox"] is None
    assert "read from a picture" in item["reply"]
    assert crop.status_code == 404


def test_a_drawing_sent_again_is_not_read_again(client: TestClient) -> None:
    first = finished(client, send(client, "", ("ctc.pdf", CTC01_PDF))["request_id"])
    reads = len(OutputsReader.reads)

    again = send(client, "What angle is dimensioned?", ("same.pdf", CTC01_PDF))
    [item] = finished(client, again["request_id"])["items"]

    assert len(OutputsReader.reads) == reads
    assert (item["values"], item["qa"]["outcome"]) == (first["items"][0]["values"], "answer")
    trace = client.get(f"/api/requests/{again['request_id']}/trace").json()["events"]
    [read] = [e for e in trace if e["step"] == "drawings.read"]
    assert read["called"] == "read cache" and read["output"]["values"] == 23
    result = client.get(f"/api/requests/{again['request_id']}/items/same/result").json()
    assert result["drawing"] == "same"
