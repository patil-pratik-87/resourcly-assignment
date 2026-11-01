from pathlib import Path

import pymupdf
import pytest

from resourcly.adapters.request_store import JsonRequestStoreAdapter
from resourcly.adapters.upload_store import FileUploadStoreAdapter
from resourcly.bootstrap import PROJECT_ROOT
from resourcly.errors import NotFound, UnsupportedUpload
from resourcly.models import RequestItem, RequestRecord, Route, Routing
from tests.conftest import CTC01, png

CTC01_PDF = (PROJECT_ROOT / "data" / "drawings" / f"{CTC01}.pdf").read_bytes()


@pytest.fixture
def uploads(tmp_path: Path) -> FileUploadStoreAdapter:
    return FileUploadStoreAdapter(tmp_path / "uploads")


def test_a_pdf_is_kept_under_its_own_name_with_its_page_count(
    uploads: FileUploadStoreAdapter,
) -> None:
    stored = uploads.save_file("r1", f"{CTC01}.pdf", CTC01_PDF)

    assert (stored.item_id, stored.name, stored.media_type) == (
        CTC01,
        f"{CTC01}.pdf",
        "application/pdf",
    )
    assert (stored.size, stored.pages) == (len(CTC01_PDF), 1)
    assert (uploads.folder("r1") / f"{CTC01}.pdf").read_bytes() == CTC01_PDF
    assert uploads.original("r1", CTC01) == (CTC01_PDF, "application/pdf")


def test_the_same_name_twice_gets_two_items(uploads: FileUploadStoreAdapter) -> None:
    first = uploads.save_file("r1", "part.pdf", CTC01_PDF)
    second = uploads.save_file("r1", "part.pdf", CTC01_PDF)

    assert (first.item_id, second.item_id) == ("part", "part-2")


def test_a_name_becomes_a_safe_item_id(uploads: FileUploadStoreAdapter) -> None:
    stored = uploads.save_file("r1", "../CTC 01 (rev A).pdf", CTC01_PDF)

    assert stored.item_id == "CTC_01_rev_A"
    assert stored.name == "CTC 01 (rev A).pdf"


def test_an_image_is_kept_and_also_stored_as_a_one_page_pdf(
    uploads: FileUploadStoreAdapter,
) -> None:
    image = png()

    stored = uploads.save_file("r1", "crack.png", image)

    assert (stored.media_type, stored.pages) == ("image/png", 1)
    assert uploads.original("r1", "crack") == (image, "image/png")
    with pymupdf.open(uploads.folder("r1") / "crack.pdf") as pdf:
        assert pdf.page_count == 1


def test_the_type_comes_from_the_bytes_not_the_name(uploads: FileUploadStoreAdapter) -> None:
    assert uploads.save_file("r1", "drawing.png", CTC01_PDF).media_type == "application/pdf"
    with pytest.raises(UnsupportedUpload, match="notes.pdf is not a PDF, PNG, JPEG or TIFF"):
        uploads.save_file("r1", "notes.pdf", b"just some text")
    with pytest.raises(UnsupportedUpload, match="broken.pdf is not a readable PDF"):
        uploads.save_file("r1", "broken.pdf", b"%PDF-1.7 and then nothing")


def test_a_missing_file_or_an_unsafe_name_is_not_found(uploads: FileUploadStoreAdapter) -> None:
    uploads.save_file("r1", "ctc.pdf", CTC01_PDF)

    for request_id, item_id in (("r1", "absent"), ("../r1", "ctc"), ("r1", "../ctc")):
        with pytest.raises(NotFound):
            uploads.original(request_id, item_id)


def _record(request_id: str, created_at: str) -> RequestRecord:
    return RequestRecord(
        request_id=request_id,
        text="read this",
        created_at=created_at,
        items=[
            RequestItem(
                item_id="ctc",
                kind="file",
                name="ctc.pdf",
                route=Routing(
                    request_id=request_id,
                    route=Route.DRAWING,
                    layer="structure",
                    confidence=1.0,
                    reason="vector PDF",
                    probabilities={},
                    elapsed_ms=3.0,
                ),
                status="queued",
            )
        ],
    )


def test_a_request_record_survives_a_new_store(tmp_path: Path) -> None:
    JsonRequestStoreAdapter(tmp_path).save(_record("r1", "2026-11-01T10:00:00.000+00:00"))

    loaded = JsonRequestStoreAdapter(tmp_path).load("r1")

    assert loaded == _record("r1", "2026-11-01T10:00:00.000+00:00")


def test_requests_list_newest_first(tmp_path: Path) -> None:
    store = JsonRequestStoreAdapter(tmp_path)
    store.save(_record("old", "2026-11-01T10:00:00.000+00:00"))
    store.save(_record("new", "2026-11-01T11:00:00.000+00:00"))
    store.save(_record("mid", "2026-11-01T10:30:00.000+00:00"))

    assert [r.request_id for r in store.list(limit=2)] == ["new", "mid"]


def test_an_unknown_request_or_result_is_not_found(tmp_path: Path) -> None:
    store = JsonRequestStoreAdapter(tmp_path)
    store.save(_record("r1", "2026-11-01T10:00:00.000+00:00"))

    for call in (
        lambda: store.load("nope"),
        lambda: store.load("../r1"),
        lambda: store.load_result("r1", "ctc"),
    ):
        with pytest.raises(NotFound):
            call()


def test_a_result_is_kept_beside_its_request(tmp_path: Path) -> None:
    store = JsonRequestStoreAdapter(tmp_path)
    store.save(_record("r1", "2026-11-01T10:00:00.000+00:00"))

    store.save_result("r1", "ctc", {"drawing": "ctc", "values": [{"raw": "Ø25"}]})

    assert JsonRequestStoreAdapter(tmp_path).load_result("r1", "ctc")["values"] == [{"raw": "Ø25"}]
