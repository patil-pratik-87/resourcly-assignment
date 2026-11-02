from io import BytesIO

from PIL import Image

from resourcly.adapters.route_pictures import picture, png
from resourcly.bootstrap import PROJECT_ROOT
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
