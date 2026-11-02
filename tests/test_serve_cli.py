"""The servers: `resourcly serve` serves the chat and the API, `annotation-ui` the label screen."""

from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from resourcly.cli import app
from tests.test_api import built


@pytest.fixture
def served(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """The app each command would serve, caught instead of run."""
    monkeypatch.setenv("RESOURCLY_UPLOADS_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("RESOURCLY_TRACE_DB", str(tmp_path / "traces.sqlite"))
    caught: dict[str, Any] = {}

    def run(server: FastAPI, host: str, port: int) -> None:
        caught.update(app=server, host=host, port=port)

    monkeypatch.setattr("resourcly.cli.uvicorn.run", run)
    return caught


def test_serve_serves_the_built_chat_and_the_api(
    served: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RESOURCLY_CHAT_UI_DIST", str(built(tmp_path / "chat", "<html>chat</html>")))

    result = CliRunner().invoke(app, ["serve", "--port", "8123"])

    assert result.exit_code == 0, result.output
    assert "Chat on http://127.0.0.1:8123" in result.output
    with TestClient(served["app"]) as client:
        assert client.get("/requests/r1/ctc").text == "<html>chat</html>"
        assert client.get("/api/agent").status_code == 200


def test_serve_says_how_to_build_the_chat_when_it_is_not_built(
    served: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RESOURCLY_CHAT_UI_DIST", str(tmp_path / "missing"))

    result = CliRunner().invoke(app, ["serve"])

    assert result.exit_code == 0, result.output
    assert "Run `npm run build` in src/frontend/chat first." in result.output
    with TestClient(served["app"]) as client:
        assert client.get("/").status_code == 404


def test_annotation_ui_serves_the_label_screen(
    served: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    labels = built(tmp_path / "labels", "<html>labels</html>")
    monkeypatch.setenv("RESOURCLY_ANNOTATION_UI_DIST", str(labels))
    monkeypatch.setenv("RESOURCLY_CHAT_UI_DIST", str(built(tmp_path / "chat", "<html>chat</html>")))

    result = CliRunner().invoke(app, ["annotation-ui"])

    assert result.exit_code == 0, result.output
    with TestClient(served["app"]) as client:
        assert client.get("/").text == "<html>labels</html>"
