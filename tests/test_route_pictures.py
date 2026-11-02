from io import BytesIO

import pymupdf
import pytest
from PIL import Image

from resourcly.adapters.route_pictures import picture, png
from resourcly.bootstrap import PROJECT_ROOT
from resourcly.errors import UnreadableAttachment
from resourcly.models import Attachment

CTC01 = PROJECT_ROOT / "data" / "drawings" / "nist_ctc_01_asme1_rd.pdf"


def image(size: tuple[int, int], mode: str = "RGB", kind: str = "PNG") -> Attachment:
    buffer = BytesIO()
    Image.new(mode, size, "white").save(buffer, kind)
    return Attachment(f"a.{kind.lower()}", f"image/{kind.lower()}", buffer.getvalue())


def test_a_pdf_is_seen_as_its_first_page_rendered_to_the_long_side() -> None:
    seen = picture(Attachment("ctc01.pdf", "application/pdf", CTC01.read_bytes()), 1024)

    assert seen.mode == "RGB"
    assert max(seen.size) == 1024
    assert seen.width > seen.height  # the sheet is landscape after its /Rotate


def test_a_large_image_shrinks_to_the_long_side_and_a_small_one_keeps_its_size() -> None:
    assert picture(image((3000, 1500)), 1024).size == (1024, 512)
    assert picture(image((300, 200)), 1024).size == (300, 200)


def test_every_picture_is_rgb() -> None:
    assert picture(image((40, 30), mode="RGBA"), 1024).mode == "RGB"
    assert picture(image((40, 30), mode="L", kind="JPEG"), 1024).mode == "RGB"


def test_png_gives_the_picture_as_png_bytes() -> None:
    data = png(image((2000, 1000)), 768)

    with Image.open(BytesIO(data)) as decoded:
        assert (decoded.format, decoded.size) == ("PNG", (768, 384))


def test_a_phone_photo_is_turned_upright_from_its_exif_orientation() -> None:
    exif = Image.Exif()
    exif[0x0112] = 6  # stored sideways: turn 90 degrees clockwise to view
    buffer = BytesIO()
    Image.new("RGB", (200, 100), "white").save(buffer, "JPEG", exif=exif)
    photo = Attachment("IMG_0001.jpg", "image/jpeg", buffer.getvalue())

    assert picture(photo, 1024).size == (100, 200)
    with Image.open(BytesIO(png(photo, 1024))) as decoded:
        assert decoded.size == (100, 200)


def truncated_jpeg() -> Attachment:
    """A JPEG cut in half: its header passes Pillow's verify(), its pixels do not decode."""
    buffer = BytesIO()
    Image.effect_noise((400, 300), 60).convert("RGB").save(buffer, "JPEG")
    data = buffer.getvalue()
    return Attachment("cut.jpg", "image/jpeg", data[: len(data) // 2])


def test_an_image_whose_pixels_do_not_decode_is_unreadable() -> None:
    with pytest.raises(
        UnreadableAttachment, match="not a readable image/jpeg image: image file is truncated"
    ):
        picture(truncated_jpeg(), 1024)


def test_a_pdf_whose_first_page_does_not_render_is_unreadable(monkeypatch) -> None:
    def broken(*args, **kwargs):
        raise RuntimeError("cannot render the page")

    monkeypatch.setattr(pymupdf.Page, "get_pixmap", broken)

    with pytest.raises(
        UnreadableAttachment, match="page 1 of the PDF cannot be rendered: cannot render the page"
    ):
        picture(Attachment("ctc01.pdf", "application/pdf", CTC01.read_bytes()), 1024)
