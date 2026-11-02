import struct
import zlib
from io import BytesIO

import pymupdf
import pytest
from PIL import Image

from resourcly.adapters.route_structure import StructureRouteAdapter
from resourcly.bootstrap import PROJECT_ROOT
from resourcly.models import Attachment, Route, guess_media_type

DRAWINGS = PROJECT_ROOT / "data" / "drawings"
REPORTS = PROJECT_ROOT / "data" / "reports"
PROSE = " ".join(["The fracture surface showed beach marks and a fatigue origin."] * 30)

rules = StructureRouteAdapter()


def pdf(name: str, data: bytes) -> Attachment:
    return Attachment(name=name, media_type="application/pdf", data=data)


def text_page(document: pymupdf.Document, text: str) -> None:
    page = document.new_page(width=612, height=792)
    page.insert_textbox(pymupdf.Rect(36, 36, 576, 756), text, fontsize=9)


def picture_page(document: pymupdf.Document, rotation: int = 0, hidden_text: str = "") -> None:
    """A page that is one big picture, as a scan saved as PDF, with an optional OCR layer."""
    page = document.new_page(width=612, height=792)
    picture = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 51, 66), False)
    picture.clear_with(200)
    page.insert_image(page.rect, pixmap=picture)
    if hidden_text:
        page.insert_textbox(page.rect + (20, 20, -20, -20), hidden_text, fontsize=9, render_mode=3)
    page.set_rotation(rotation)


def built(*pages) -> Attachment:
    document = pymupdf.open()
    for add, *args in pages:
        add(document, *args)
    return pdf("built.pdf", document.tobytes())


def test_a_request_with_no_attachment_is_a_text_question() -> None:
    verdict = rules.decide(None)

    assert (verdict.route, verdict.confidence, verdict.reason) == (Route.TEXT, 1.0, "no attachment")


def test_a_cad_pdf_is_a_drawing_from_its_vector_paths() -> None:
    verdict = rules.decide(pdf("ctc01.pdf", (DRAWINGS / "nist_ctc_01_asme1_rd.pdf").read_bytes()))

    assert verdict.route == Route.DRAWING
    assert verdict.reason == "vector PDF, 1797 paths on page 1"


def test_a_report_pdf_is_a_document_that_fits_no_case() -> None:
    report = sorted(REPORTS.glob("*.pdf"))[0]

    verdict = rules.decide(pdf(report.name, report.read_bytes()))

    assert verdict.route == Route.OTHER
    assert verdict.reason.startswith("prose PDF, 0 CAD sheets and ")


def test_a_drawing_package_with_a_cover_and_notes_sheet_is_a_drawing() -> None:
    package = pymupdf.open()
    text_page(package, "DRAWING PACKAGE\nPART NUMBER: FTC-06-1000")
    text_page(package, PROSE)
    with pymupdf.open(DRAWINGS / "nist_ftc_06_asme1_rd.pdf") as sheets:
        package.insert_pdf(sheets)

    verdict = rules.decide(pdf("package.pdf", package.tobytes()))

    assert verdict.route == Route.DRAWING
    assert verdict.reason == "drawing package, 3 CAD sheets and 1 prose page in the first 10"


@pytest.mark.parametrize("rotation", [0, 270])
def test_a_scan_is_left_to_the_probe_even_with_an_ocr_text_layer(rotation: int) -> None:
    verdict = rules.decide(built((picture_page, rotation, PROSE)))

    assert verdict.route is None
    assert verdict.reason == "page 1 is a picture covering 100% of it; the picture decides"


def test_a_short_pdf_with_no_vectors_or_picture_is_left_to_the_probe() -> None:
    verdict = rules.decide(built((text_page, "A cover page with a title only.")))

    assert verdict.route is None
    assert verdict.reason == (
        "PDF with 0 CAD sheets and 0 prose pages in the first 10, and no full-page picture"
    )


def png_bytes(size: tuple[int, int] = (40, 30)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", size, "white").save(buffer, "PNG")
    return buffer.getvalue()


def png_header(width: int, height: int) -> bytes:
    """A PNG that claims a size in its header and holds no pixels, as a decompression bomb does."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        crc = struct.pack(">I", zlib.crc32(kind + data))
        return struct.pack(">I", len(data)) + kind + data + crc

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(b""))
        + chunk(b"IEND", b"")
    )


def test_an_image_is_left_to_the_probe() -> None:
    verdict = rules.decide(Attachment("part.png", "image/png", png_bytes()))

    assert (verdict.route, verdict.reason) == (None, "an image; the picture decides")


def corrupt_png() -> bytes:
    data = bytearray(png_bytes())
    data[-20:-12] = b"\x00" * 8  # break the pixel data and its checksum
    return bytes(data)


@pytest.mark.parametrize(
    ("name", "media_type", "data"),
    [
        ("broken.png", "image/png", corrupt_png()),
        ("truncated.png", "image/png", png_bytes()[:60]),
        ("logo.svg", "image/svg+xml", b'<svg xmlns="http://www.w3.org/2000/svg"></svg>'),
        ("IMG_0001.heic", "image/heic", b"\x00\x00\x00\x18ftypheic" + b"\x00" * 64),
    ],
    ids=["corrupt", "truncated", "svg", "heic"],
)
def test_an_image_that_cannot_be_read_fits_no_case(name: str, media_type: str, data: bytes) -> None:
    verdict = rules.decide(Attachment(name, media_type, data))

    assert (verdict.route, verdict.confidence) == (Route.OTHER, 1.0)
    assert verdict.reason == f"not a readable {media_type} image"


def test_an_image_with_too_many_pixels_fits_no_case() -> None:
    verdict = rules.decide(Attachment("bomb.png", "image/png", png_header(20000, 20000)))

    assert verdict.route == Route.OTHER
    assert verdict.reason == "an image over 89478485 pixels, too many to read safely"


def test_a_file_that_is_neither_a_pdf_nor_an_image_fits_no_case() -> None:
    verdict = rules.decide(Attachment("notes.txt", "text/plain", b"hello"))

    assert verdict.route == Route.OTHER
    assert verdict.reason == "a text/plain file is neither a PDF nor an image"


def test_an_unreadable_pdf_fits_no_case() -> None:
    verdict = rules.decide(pdf("broken.pdf", b"%PDF-1.7\nnot really"))

    assert (verdict.route, verdict.reason) == (Route.OTHER, "not a readable PDF")


@pytest.mark.parametrize(
    ("name", "data", "media_type"),
    [
        ("scan.bin", b"%PDF-1.7\n", "application/pdf"),
        ("photo", b"\xff\xd8\xff\xe0rest", "image/jpeg"),
        ("x.dat", b"\x89PNG\r\n\x1a\nrest", "image/png"),
        ("sheet.tif", b"II*\x00rest", "image/tiff"),
        ("page.webp", b"RIFF\x00\x00\x00\x00WEBPrest", "image/webp"),
        ("notes.txt", b"hello", "text/plain"),
        ("blob", b"\x00\x01", "application/octet-stream"),
    ],
)
def test_the_media_type_comes_from_the_bytes_before_the_name(
    name: str, data: bytes, media_type: str
) -> None:
    assert guess_media_type(name, data) == media_type
