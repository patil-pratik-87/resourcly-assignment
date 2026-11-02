"""The chat from the command line: `resourcly ask`, `request` and `requests`."""

import json
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner, Result

from resourcly.bootstrap import PROJECT_ROOT, Settings, open_services
from resourcly.cli import app
from tests.conftest import CTC01, png

DRAWING = PROJECT_ROOT / "data" / "drawings" / f"{CTC01}.pdf"


@pytest.fixture(autouse=True)
def stores(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RESOURCLY_UPLOADS_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("RESOURCLY_TRACE_DB", str(tmp_path / "traces.sqlite"))
    # the model-free router, so the commands run without the router's models
    monkeypatch.setenv("RESOURCLY_ROUTER_VERSION", "stub-v0")


def invoke(*args: str) -> Result:
    return CliRunner().invoke(app, list(args))


def request_id(result: Result) -> str:
    return re.search(r"^request ([0-9a-f]{32})", result.output, re.MULTILINE)[1]


def test_ask_reads_a_drawing_and_writes_its_json(tmp_path: Path) -> None:
    result = invoke("ask", "read this", "--file", str(DRAWING), "--out", str(tmp_path / "out"))

    assert result.exit_code == 0, result.output
    assert f"{CTC01}: drawing (stub, 0.7), done" in result.output
    assert "6 values, 0 issues" in result.output
    saved = json.loads((tmp_path / "out" / f"{CTC01}.json").read_text(encoding="utf-8"))
    assert saved["drawing"] == CTC01 and len(saved["values"]) == 6


def test_ask_with_a_folder_uploads_every_file_in_it_as_one_request(tmp_path: Path) -> None:
    folder = tmp_path / "batch"
    folder.mkdir()
    (folder / "a.pdf").write_bytes(DRAWING.read_bytes())
    (folder / "b.pdf").write_bytes(DRAWING.read_bytes())
    (folder / "crack.png").write_bytes(png())
    (folder / ".DS_Store").write_bytes(b"hidden")

    result = invoke("ask", "--file", str(folder))

    assert result.exit_code == 0, result.output
    assert "a: drawing (stub, 0.7), done" in result.output
    assert "b: drawing (stub, 0.7), done" in result.output
    assert "crack: photo (stub, 0.6), answered" in result.output
    assert "The closest report figure is" in result.output
    assert ".DS_Store" not in result.output


def test_ask_with_text_alone_gets_the_text_reply() -> None:
    result = invoke("ask", "why did the bracket crack?")

    assert result.exit_code == 0, result.output
    assert "message: text (stub, 1.0), answered" in result.output
    assert "Answering questions from the NTSB reports is not available yet." in result.output


def test_ask_with_nothing_is_refused() -> None:
    result = invoke("ask")

    assert result.exit_code == 1
    assert "Send some text, a file, or both." in result.output


def test_a_failed_item_makes_ask_exit_with_1(tmp_path: Path) -> None:
    notes = tmp_path / "notes.txt"
    notes.write_text("plain text", encoding="utf-8")

    result = invoke("ask", "--file", str(notes))

    assert result.exit_code == 1
    assert "rejected-1 (notes.txt): failed" in result.output
    assert "notes.txt is not a PDF, PNG, JPEG or TIFF file" in result.output


def test_request_shows_the_record_and_every_step_it_took() -> None:
    sent = request_id(invoke("ask", "read", "--file", str(DRAWING)))

    result = invoke("request", sent)

    assert result.exit_code == 0, result.output
    assert f"request {sent}  done" in result.output
    assert f"{CTC01}: drawing (stub, 0.7), done" in result.output
    steps = re.findall(r"^  \S+  (\S+)  called (.+?)  [\d.]+ ms$", result.output, re.MULTILINE)
    assert steps == [
        ("requests.receive", "agent"),
        ("uploads.save", "upload store"),
        ("route.stub", "router stub-v0 (stub): stand-in structure rule, no model"),
        ("router.route", "router stub-v0 (stub)"),
        ("drawings.read", "reader textlayer-v0 (textlayer)"),
    ]


def test_request_can_write_the_drawing_json(tmp_path: Path) -> None:
    sent = request_id(invoke("ask", "--file", str(DRAWING)))

    result = invoke("request", sent, "--out", str(tmp_path / "out"))

    assert result.exit_code == 0, result.output
    assert (tmp_path / "out" / f"{CTC01}.json").is_file()


def test_a_request_with_steps_but_no_record_shows_its_steps() -> None:
    with open_services(Settings.from_env()) as services:
        services.drawings.read(CTC01, request_id="reader-run:case")

    result = invoke("request", "reader-run:case")

    assert result.exit_code == 0, result.output
    assert "trace: 1 step(s)" in result.output
    assert "drawings.read  called reader textlayer-v0 (textlayer)" in result.output
    assert f'input   {{"drawing": "{CTC01}"}}' in result.output
    assert 'output  {"values": 6, "schema_issues": 0, "answer_issues": 0}' in result.output


def test_an_unknown_request_is_a_short_error() -> None:
    result = invoke("request", "absent")

    assert result.exit_code == 1
    assert result.output.strip() == "error: no request 'absent'"


def test_requests_lists_the_latest_first() -> None:
    first = request_id(invoke("ask", "first"))
    second = request_id(invoke("ask", "second", "--file", str(DRAWING)))

    result = invoke("requests", "--limit", "5")

    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert [line.split()[0] for line in lines] == [second, first]
    assert lines[0].split()[1:4] == ["done", "1", "item(s)"]
    assert lines[1].endswith('"first"')


def test_serve_runs_the_api_on_the_given_port(monkeypatch: pytest.MonkeyPatch) -> None:
    served = {}
    monkeypatch.setattr("resourcly.cli.uvicorn.run", lambda app, **where: served.update(where))

    result = invoke("serve", "--port", "8123")

    assert result.exit_code == 0, result.output
    assert served == {"host": "127.0.0.1", "port": 8123}
    assert "Chat on http://127.0.0.1:8123" in result.output
    assert "reader textlayer-v0, router stub-v0" in result.output


def test_ask_with_a_photo_prints_the_answer_its_citations_and_the_closest_figures(
    tmp_path: Path,
) -> None:
    photo = tmp_path / "crack.png"
    photo.write_bytes(png())

    result = invoke("ask", "what is wrong?", "--file", str(photo))

    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    start = lines.index("  crack: photo (stub, 0.6), answered")
    answer = lines[start + 1 :]
    assert answer[0].startswith("    The closest report figure is")
    assert "    From the reports:" in answer
    assert any(re.match(r"    - Figure \d+\. .* \[\d\d-\d\d\d fig\d\d\]$", line) for line in answer)
    assert any(line.startswith("    Closest report figures: ") for line in answer)


def test_request_shows_the_retrieval_and_answer_steps_of_a_photo(tmp_path: Path) -> None:
    photo = tmp_path / "crack.png"
    photo.write_bytes(png())
    sent = invoke("ask", "--file", str(photo))

    result = invoke("request", request_id(sent))

    assert result.exit_code == 0, result.output
    assert "failure.find  called finder shuffled-v0 (shuffled)" in result.output
    assert "answer.photo  called answer captions-v0 (captions)" in result.output
