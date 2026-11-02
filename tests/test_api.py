import json
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from resourcly.api import create_app
from resourcly.bootstrap import Settings
from tests.conftest import CTC01


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as client:
        yield client


def test_lists_every_pdf_with_gold_counts(client: TestClient) -> None:
    drawings = {row["drawing"]: row for row in client.get("/api/drawings").json()}

    assert len(drawings) == 11
    assert drawings[CTC01] | {} == {
        "drawing": CTC01,
        "page_count": 1,
        "has_gold": True,
        "source": "drawings",
        "values": 17,
        "approved": 0,
        "issues": 0,
    }
    assert drawings["nist_ftc_06_asme1_rd"]["has_gold"] is False
    assert drawings["nist_ftc_06_asme1_rd"]["page_count"] == 3


def test_get_returns_the_stored_document(client: TestClient, ctc01: dict) -> None:
    assert client.get(f"/api/drawings/{CTC01}").json() == ctc01


def test_get_without_gold_returns_an_empty_document(client: TestClient) -> None:
    document = client.get("/api/drawings/nist_ftc_06_asme1_rd").json()

    assert document["page_count"] == 3
    assert document["values"] == [] and document["features"] == []


def test_put_saves_a_valid_document(client: TestClient, ctc01: dict, gold_dir: Path) -> None:
    ctc01["values"][0]["status"] = "approved"

    response = client.put(f"/api/drawings/{CTC01}", json=ctc01)

    assert response.status_code == 200
    saved = json.loads((gold_dir / "drawings" / f"{CTC01}.json").read_text(encoding="utf-8"))
    assert saved["values"][0]["status"] == "approved"
    summary = next(row for row in client.get("/api/drawings").json() if row["drawing"] == CTC01)
    assert summary["approved"] == 1


def test_put_rejects_an_invalid_document_without_writing(
    client: TestClient, ctc01: dict, gold_dir: Path
) -> None:
    path = gold_dir / "drawings" / f"{CTC01}.json"
    before = path.read_text(encoding="utf-8")
    ctc01["values"][5]["unit"] = "furlong"

    response = client.put(f"/api/drawings/{CTC01}", json=ctc01)

    assert response.status_code == 422
    assert [issue["loc"] for issue in response.json()["issues"]] == [["values", 5, "unit"]]
    assert path.read_text(encoding="utf-8") == before


def test_put_rejects_a_document_for_another_drawing(client: TestClient, ctc01: dict) -> None:
    response = client.put("/api/drawings/nist_ctc_02_asme1_rc", json=ctc01)

    assert response.status_code == 422
    assert response.json()["issues"][0]["loc"] == ["drawing"]


def test_check_reports_issues_without_saving(client: TestClient, ctc01: dict) -> None:
    ctc01["page_count"] = 2

    response = client.post(f"/api/drawings/{CTC01}/check", json=ctc01)

    assert response.json() == [{"loc": ["page_count"], "message": "the PDF has 1 page(s)"}]


def test_page_renders_as_png(client: TestClient) -> None:
    response = client.get(f"/api/drawings/{CTC01}/pages/1.png?dpi=50")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content.startswith(b"\x89PNG")


@pytest.mark.parametrize(
    "url", [f"/api/drawings/{CTC01}/pages/2.png", "/api/drawings/unknown", "/api/drawings/..%2Fx"]
)
def test_unknown_drawings_and_pages_are_404(client: TestClient, url: str) -> None:
    assert client.get(url).status_code == 404


def test_undefined_datums_block_a_full_gold_drawing_but_not_partial_gold(
    client: TestClient, ctc01: dict, gold_dir: Path
) -> None:
    ctc01["values"][4]["datums"] = ["A", "Z"]

    issues = client.post(f"/api/drawings/{CTC01}/check", json=ctc01).json()
    assert [issue["loc"] for issue in issues] == [["values", 4, "datums"]]

    (gold_dir / "partial").mkdir()
    (gold_dir / "drawings" / f"{CTC01}.json").rename(gold_dir / "partial" / f"{CTC01}.json")
    assert client.post(f"/api/drawings/{CTC01}/check", json=ctc01).json() == []


def test_corrupt_pdf_page_is_422(settings: Settings, tmp_path: Path) -> None:
    drawings = tmp_path / "pdfs"
    drawings.mkdir()
    (drawings / "broken.pdf").write_bytes(b"%PDF-1.4 not really")
    with TestClient(create_app(replace(settings, drawings_dir=drawings))) as client:
        response = client.get("/api/drawings/broken/pages/1.png")

    assert response.status_code == 422
    assert response.json() == {"detail": "broken.pdf is not a readable PDF"}


def test_a_page_limited_drawing_may_name_datums_from_other_pages(
    client: TestClient, ctc01: dict
) -> None:
    ctc01["values"][4]["datums"] = ["A", "Z"]
    page_limited = {"drawing": ctc01.pop("drawing"), "page_count": 1, "page_coverage": [1], **ctc01}

    assert client.post(f"/api/drawings/{CTC01}/check", json=page_limited).json() == []


def built(folder: Path, page: str) -> Path:
    """A built screen of one page, as `npm run build` leaves it."""
    (folder / "assets").mkdir(parents=True)
    (folder / "index.html").write_text(page, encoding="utf-8")
    (folder / "assets" / "app.js").write_text("run()", encoding="utf-8")
    return folder


def test_the_built_chat_is_served_at_the_root_and_at_each_of_its_addresses(
    settings: Settings, tmp_path: Path
) -> None:
    dist = built(tmp_path / "chat", "<html>chat</html>")

    with TestClient(create_app(replace(settings, chat_ui_dist=dist))) as client:
        pages = [client.get(path) for path in ("/", "/chat", "/requests", "/requests/r1/ctc")]
        script = client.get("/assets/app.js")
        agent = client.get("/api/agent")
        missing = client.get("/api/requests/nope")

    assert [(page.status_code, page.text) for page in pages] == [(200, "<html>chat</html>")] * 4
    assert (script.status_code, script.text) == (200, "run()")
    assert agent.json()["router"] == "stub-v0 (stub)"
    assert missing.status_code == 404 and "detail" in missing.json()


def test_the_label_screen_is_served_instead_when_asked_for(
    settings: Settings, tmp_path: Path
) -> None:
    labels = built(tmp_path / "annotation", "<html>labels</html>")
    chat = built(tmp_path / "chat", "<html>chat</html>")
    both = replace(settings, annotation_ui_dist=labels, chat_ui_dist=chat)

    with TestClient(create_app(both, screen="annotation")) as client:
        page = client.get("/")
        chat_page = client.get("/chat")
        drawings = client.get("/api/drawings")

    assert (page.status_code, page.text) == (200, "<html>labels</html>")
    assert chat_page.status_code == 404
    assert drawings.status_code == 200


def test_without_a_built_screen_only_the_api_is_served(client: TestClient) -> None:
    assert client.get("/").status_code == 404
    assert client.get("/api/agent").status_code == 200
