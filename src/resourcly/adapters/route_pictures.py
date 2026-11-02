from io import BytesIO

import pymupdf
from PIL import Image, ImageOps

from resourcly.adapters.route_structure import is_pdf
from resourcly.models import Attachment


def picture(attachment: Attachment, max_side: int) -> Image.Image:
    """What a router model sees of an attachment, in RGB: an image, or page 1 of a PDF.

    A PDF page is rendered so that its long side is max_side. An image is first turned upright
    from its EXIF orientation, as a phone photo taken in portrait is stored sideways. One larger
    than max_side then shrinks to it, and a smaller one keeps its size.
    """
    if is_pdf(attachment):
        with pymupdf.open(stream=attachment.data, filetype="pdf") as document:
            page = document[0]
            zoom = max_side / max(page.rect.width, page.rect.height)
            pixmap = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
            return Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
    with Image.open(BytesIO(attachment.data)) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")
    if max(image.size) > max_side:
        image.thumbnail((max_side, max_side), Image.Resampling.BICUBIC)
    return image


def png(attachment: Attachment, max_side: int) -> bytes:
    buffer = BytesIO()
    picture(attachment, max_side).save(buffer, "PNG")
    return buffer.getvalue()
