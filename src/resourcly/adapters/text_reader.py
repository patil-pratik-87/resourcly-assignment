import re
from pathlib import Path
from typing import Any

import pymupdf

from resourcly.errors import NotFound, UnreadableDrawing
from resourcly.models import drawing_short
from resourcly.ports import Progress

Box = tuple[float, float, float, float]

NUMBERED = re.compile(r"^\d+\.(\s|$)")
WORD = re.compile(r"\S*[A-Za-z]\S*[A-Za-z]\S*")


class PyMuPDFTextReaderAdapter:
    """Reads the PDF text layer: title block entries and notes, never the drawn callouts.

    A text block in the sheet border is the title block, one record per line. Elsewhere a block of
    prose is a note, split at numbered items. A one-line heading ending in ":" is neither, and short
    text such as "Ø.250 +.003" is skipped, so the values this reader finds are the ones any reader
    gets for free.
    """

    def __init__(self, folder: Path):
        self.folder = folder

    def read(self, drawing: str, progress: Progress | None = None) -> dict[str, Any]:
        """The text layer is read in one step, so there is no progress to report."""
        path = self.folder / f"{drawing}.pdf"
        if not path.is_file():
            raise NotFound(f"no drawing named {drawing}")
        try:
            pdf = pymupdf.open(path)
        except pymupdf.FileDataError as error:
            raise UnreadableDrawing(f"{path.name} is not a readable PDF") from error
        with pdf:
            found = [record for page in pdf for record in text_records(page)]
            page_count = pdf.page_count
        prefix = drawing_short(drawing) or "rec"
        values = [
            _value(f"{prefix}-{index:02d}", *record) for index, record in enumerate(found, start=1)
        ]
        return {"drawing": drawing, "page_count": page_count, "title_block": {}, "values": values}


def text_records(page: pymupdf.Page) -> list[tuple[int, str, str, Box]]:
    """The title block entries and notes on the page: (page, callout, text, box) each."""
    records = []
    for block in page.get_text("dict")["blocks"]:
        lines = [found for line in block.get("lines", []) if (found := _line(page, line))[0]]
        if not lines or _heading(lines):
            continue
        if _in_border(_union(box for _, box in lines)):
            records += [(page.number + 1, "title_block", text, box) for text, box in lines]
            continue
        for item in _items(lines):
            text = " ".join(text for text, _ in item)
            words = len(WORD.findall(text))
            if _heading(item):
                continue
            if (NUMBERED.match(text) and words) or words >= 4:
                records.append((page.number + 1, "note", text, _union(box for _, box in item)))
    return records


def _heading(lines: list[tuple[str, Box]]) -> bool:
    return len(lines) == 1 and lines[0][0].endswith(":")


def _line(page: pymupdf.Page, line: dict) -> tuple[str, Box]:
    text = " ".join(" ".join(span["text"] for span in line["spans"]).split())
    rect = pymupdf.Rect(line["bbox"]) * page.rotation_matrix
    width, height = page.rect.width, page.rect.height
    return text, (rect.x0 / width, rect.y0 / height, rect.x1 / width, rect.y1 / height)


def _items(lines: list[tuple[str, Box]]) -> list[list[tuple[str, Box]]]:
    items: list[list[tuple[str, Box]]] = []
    for text, box in lines:
        if not items or NUMBERED.match(text):
            items.append([])
        items[-1].append((text, box))
    return items


def _in_border(box: Box) -> bool:
    x0, y0, _, y1 = box
    return y1 <= 0.12 or y0 >= 0.9 or x0 >= 0.95


def _union(boxes) -> Box:
    x0, y0, x1, y1 = zip(*boxes, strict=True)
    return min(x0), min(y0), max(x1), max(y1)


def _value(record_id: str, page: int, callout: str, text: str, box: Box) -> dict[str, Any]:
    return {
        "id": record_id,
        "raw": text,
        "callout": callout,
        "kind": callout,
        "tolerance_style": "none",
        "value": None,
        "unit": None,
        "feature_id": None,
        "datums": [],
        "limits": None,
        "meaning": "",
        "page": page,
        "bbox": [round(edge, 3) for edge in box],
        "confidence": None,
    }
