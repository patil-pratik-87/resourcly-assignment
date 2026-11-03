import threading
from pathlib import Path

import pymupdf

from resourcly.errors import NotFound, UnreadableDrawing


class PyMuPDFPageAdapter:
    """Renders pages of the PDFs in one folder; a drawing is a PDF file stem.

    Open documents are kept until close() and reopened when the file changes. PyMuPDF documents are
    not thread safe, so one lock serialises access.
    """

    def __init__(self, folder: Path):
        self.folder = folder
        self._open: dict[str, tuple[float, pymupdf.Document]] = {}
        self._lock = threading.Lock()

    def list_drawings(self) -> list[str]:
        return sorted(path.stem for path in self.folder.glob("*.pdf"))

    def page_count(self, drawing: str) -> int:
        with self._lock:
            return self._document(drawing).page_count

    def render(
        self,
        drawing: str,
        page: int,
        dpi: int,
        clip: tuple[float, float, float, float] | None = None,
    ) -> bytes:
        with self._lock:
            found = self._page(drawing, page)
            area = pymupdf.Rect(clip) & found.rect if clip else None
            try:
                return found.get_pixmap(dpi=dpi, clip=area).tobytes("png")
            except RuntimeError as error:
                raise UnreadableDrawing(f"{drawing} page {page} cannot be rendered") from error

    def page_size(self, drawing: str, page: int) -> tuple[float, float]:
        with self._lock:
            rect = self._page(drawing, page).rect
            return rect.width, rect.height

    def _page(self, drawing: str, page: int) -> pymupdf.Page:
        pdf = self._document(drawing)
        if not 1 <= page <= pdf.page_count:
            raise NotFound(f"{drawing} has no page {page}")
        return pdf[page - 1]

    def close(self) -> None:
        with self._lock:
            for _, pdf in self._open.values():
                pdf.close()
            self._open.clear()

    def _document(self, drawing: str) -> pymupdf.Document:
        path = self.folder / f"{drawing}.pdf"
        if not path.is_file():
            raise NotFound(f"no drawing named {drawing}")
        modified = path.stat().st_mtime
        cached = self._open.get(drawing)
        if cached and cached[0] == modified:
            return cached[1]
        if cached:
            cached[1].close()
            del self._open[drawing]
        try:
            pdf = pymupdf.open(path)
        except pymupdf.FileDataError as error:
            raise UnreadableDrawing(f"{path.name} is not a readable PDF") from error
        self._open[drawing] = (modified, pdf)
        return pdf
