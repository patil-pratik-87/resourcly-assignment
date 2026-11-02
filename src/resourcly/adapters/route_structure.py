import warnings
from io import BytesIO

import pymupdf
from PIL import Image

from resourcly.models import Attachment, LayerVerdict, Route


def is_pdf(attachment: Attachment) -> bool:
    return attachment.media_type == "application/pdf"


def is_image(attachment: Attachment) -> bool:
    return attachment.media_type.startswith("image/")


class StructureRouteAdapter:
    """Layer 1 of the router: rules on the request's structure, read with PyMuPDF and no model.

    No attachment is a text question. A PDF whose page 1 is CAD line art (many vector paths, little
    picture) is a drawing, and so is one whose first pages hold at least as many CAD sheets as
    pages of prose, such as a drawing package with a cover and a notes sheet. A PDF with more prose
    pages fits no case. A page that is one big picture never counts as prose, so the OCR text layer
    of a scan cannot make it a document. Images and scans pass on to the next layer, once the image
    is known to open: one that cannot be read, or that claims too many pixels to decode safely,
    fits no case.
    """

    name = "structure"

    def __init__(
        self,
        vector_paths: int = 300,
        cad_max_picture: float = 0.2,
        prose_chars: int = 1000,
        full_page_picture: float = 0.9,
        raster_picture: float = 0.5,
        pages: int = 10,
    ):
        self.vector_paths = vector_paths
        self.cad_max_picture = cad_max_picture
        self.prose_chars = prose_chars
        self.full_page_picture = full_page_picture
        self.raster_picture = raster_picture
        self.pages = pages

    @property
    def called(self) -> str:
        return f"PyMuPDF structure rules ({self.vector_paths} paths, first {self.pages} pages)"

    def decide(self, attachment: Attachment | None) -> LayerVerdict:
        if attachment is None:
            return LayerVerdict(Route.TEXT, "no attachment", 1.0)
        if is_image(attachment):
            return self._decide_image(attachment)
        if not is_pdf(attachment):
            return LayerVerdict(
                Route.OTHER,
                f"a {attachment.media_type} file is neither a PDF nor an image",
                1.0,
            )
        try:
            with pymupdf.open(stream=attachment.data, filetype="pdf") as document:
                return self._decide_pdf(document)
        except (pymupdf.FileDataError, RuntimeError, ValueError):
            return LayerVerdict(Route.OTHER, "not a readable PDF", 1.0)

    @staticmethod
    def _decide_image(attachment: Attachment) -> LayerVerdict:
        try:
            # a picture over Pillow's pixel limit warns at first and raises at twice the limit,
            # so both are refused before anything decodes it
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(BytesIO(attachment.data)) as image:
                    image.verify()
        except (Image.DecompressionBombError, Image.DecompressionBombWarning):
            return LayerVerdict(
                Route.OTHER,
                f"an image over {Image.MAX_IMAGE_PIXELS} pixels, too many to read safely",
                1.0,
            )
        except (OSError, SyntaxError, ValueError):
            return LayerVerdict(Route.OTHER, f"not a readable {attachment.media_type} image", 1.0)
        return LayerVerdict(None, "an image; the picture decides")

    def _decide_pdf(self, document: pymupdf.Document) -> LayerVerdict:
        if document.page_count == 0:
            return LayerVerdict(Route.OTHER, "not a readable PDF", 1.0)
        # page 1 alone decides most CAD exports, so the other pages are read only when it does not
        first = self._layout(document[0])
        if self._cad_sheet(*first):
            return LayerVerdict(Route.DRAWING, f"vector PDF, {first[0]} paths on page 1", 1.0)
        layouts = [first, *(self._layout(document[i]) for i in range(1, self._read(document)))]
        sheets = sum(1 for layout in layouts if self._cad_sheet(*layout))
        prose = sum(1 for layout in layouts if self._prose(*layout))
        kinds = (
            f"{sheets} CAD sheet{'s' * (sheets != 1)} and {prose} prose"
            f" page{'s' * (prose != 1)} in the first {self.pages}"
        )
        if sheets and sheets >= prose:
            return LayerVerdict(Route.DRAWING, f"drawing package, {kinds}", 1.0)
        cover = first[2]
        if cover >= self.raster_picture:
            return LayerVerdict(
                None, f"page 1 is a picture covering {cover:.0%} of it; the picture decides"
            )
        if prose:
            return LayerVerdict(Route.OTHER, f"prose PDF, {kinds}", 1.0)
        return LayerVerdict(None, f"PDF with {kinds}, and no full-page picture")

    def _read(self, document: pymupdf.Document) -> int:
        return min(self.pages, document.page_count)

    def _cad_sheet(self, paths: int, chars: int, cover: float) -> bool:
        return paths >= self.vector_paths and cover < self.cad_max_picture

    def _prose(self, paths: int, chars: int, cover: float) -> bool:
        return (
            not self._cad_sheet(paths, chars, cover)
            and chars >= self.prose_chars
            and cover < self.full_page_picture
        )

    @staticmethod
    def _layout(page: pymupdf.Page) -> tuple[int, int, float]:
        """A page's vector paths, characters of text and the share of its area under pictures."""
        area = page.rect.width * page.rect.height
        cover = 0.0
        # get_image_info() gives the picture boxes in about 0.3 ms where get_image_rects() takes 20
        # to 40 ms on a page that is one picture. The boxes are in unrotated page space and
        # page.rect in the rotated view, and the NIST sheets carry /Rotate 270.
        for info in page.get_image_info():
            box = (pymupdf.Rect(info["bbox"]) * page.rotation_matrix) & page.rect
            cover += max(0.0, box.width) * max(0.0, box.height)
        return len(page.get_cdrawings()), len(page.get_text().strip()), min(1.0, cover / area)
