"""Cuts an NTSB materials laboratory report into its figures and paragraphs, with PyMuPDF.

The layout rule, checked on all 46 figures of the three reports:

1. Keep the pictures larger than 200 by 200 points, and drop a picture that lies inside another,
   such as an arrow or a label drawn over a photo.
2. Sort the captions ("Figure N. ...") by their bottom edge, and give each picture to the first
   caption whose bottom is at or below the picture's top. That holds for a caption below a picture
   and for one beside it.
3. A figure's box is the union of its pictures; the labels drawn on them fall inside it.

A paragraph is a text block outside the figures, without the page headers. One that starts in
lower case continues the paragraph of the page before, so the two are joined.
"""

import re
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from resourcly.models import Passage

MIN_PICTURE = 200 * 200  # square points
MIN_PARAGRAPH = 40  # characters; shorter blocks are labels or signatures
CLOSING = 2  # the last body paragraphs kept as the report's closing
CAPTION = re.compile(r"^Figure\s+(\d+)\.\s*(.*)", re.S)
CITED = re.compile(r"\bfigures?\s+(\d+)(?:\s*(?:and|,|through|-)\s*(\d+))?", re.I)
HEADER = re.compile(r"(Report No\.|Page No\.|Pg \d+ of \d+|MATERIALS LABORATORY\s*$)")
SIGNATURE = re.compile(r"^(Submitted by|[A-Z][a-z]+ [A-Z]\. [A-Z][a-z]+)")
REPORT_ID = re.compile(r"(\d{2}-\d{3})")
FIELDS = {
    "vehicle": r"Vehicle\s*:?\s*(.+?)\s+(?:NTSB No|Investigator|B\.)",
    "components": r"COMPONENTS EXAMINED\s*(.+?)\s+C\.\s",
}

Box = tuple[float, float, float, float]


@dataclass(frozen=True)
class CutFigure:
    figure: str  # <report>/fig<nn>, such as 18-061/fig05
    report: str
    number: int
    page: int  # from 1
    bbox: Box  # in PDF points
    caption: str
    citing: list[Passage]  # the paragraphs that name the figure, in report order


@dataclass(frozen=True)
class CutReport:
    report: str
    vehicle: str | None
    components: str | None
    figures: list[CutFigure]
    paragraphs: list[Passage]
    closing: list[Passage]  # the last paragraphs before the first figure


@dataclass
class _Paragraph:
    page: int
    text: str


def cut_report(pdf: Path) -> CutReport:
    match = REPORT_ID.search(pdf.stem)
    report = match.group(1) if match else pdf.stem
    found: list[tuple[int, int, Box, str]] = []  # number, page, box, caption
    paragraphs: list[_Paragraph] = []
    first_text: list[str] = []
    with pymupdf.open(pdf) as document:
        for page in document:
            figures, texts = _page_layout(page)
            found += [(number, page.number + 1, box, caption) for number, box, caption in figures]
            first_text += texts
            for text in texts:
                if HEADER.search(text):
                    continue
                if text[:1].islower() and paragraphs:
                    paragraphs[-1].text += f" {text}"
                elif len(text) >= MIN_PARAGRAPH and not SIGNATURE.match(text):
                    paragraphs.append(_Paragraph(page.number + 1, text))
    passages = [Passage(report=report, page=p.page, text=p.text) for p in paragraphs]
    figures = [
        CutFigure(
            figure=f"{report}/fig{number:02d}",
            report=report,
            number=number,
            page=page,
            bbox=box,
            caption=caption,
            citing=[passage for passage in passages if number in _cited(passage.text)],
        )
        for number, page, box, caption in found
    ]
    first_figure = min((figure.page for figure in figures), default=10**6)
    body = [passage for passage in passages if passage.page < first_figure]
    flat = re.sub(r"\s+", " ", " ".join(first_text[:80]))
    fields = {name: re.search(pattern, flat) for name, pattern in FIELDS.items()}
    return CutReport(
        report=report,
        vehicle=fields["vehicle"].group(1).strip(" :") if fields["vehicle"] else None,
        components=fields["components"].group(1).strip(" :") if fields["components"] else None,
        figures=figures,
        paragraphs=passages,
        closing=body[-CLOSING:],
    )


def render_figure(pdf: Path, page: int, bbox: Box, dpi: int) -> bytes:
    """A figure's box on its page, from 1, as a PNG."""
    with pymupdf.open(pdf) as document:
        pixmap = document[page - 1].get_pixmap(clip=pymupdf.Rect(bbox), dpi=dpi, alpha=False)
        return pixmap.tobytes("png")


def _page_layout(page: pymupdf.Page) -> tuple[list[tuple[int, Box, str]], list[str]]:
    """The page's figures (number, box, caption) and the text of its other blocks."""
    pictures: list[Box] = []
    captions: list[tuple[Box, int, str]] = []
    texts: list[tuple[Box, str]] = []
    for block in page.get_text("dict")["blocks"]:
        if block["type"] == 1:
            if block["width"] * block["height"] > MIN_PICTURE:
                pictures.append(tuple(block["bbox"]))
            continue
        text = " ".join(span["text"] for line in block["lines"] for span in line["spans"]).strip()
        text = re.sub(r"\s+", " ", text)
        if not text:
            continue
        caption = CAPTION.match(text)
        if caption:
            captions.append((tuple(block["bbox"]), int(caption.group(1)), text))
        else:
            texts.append((tuple(block["bbox"]), text))
    pictures = [p for p in pictures if not any(p != o and _inside(p, o) for o in pictures)]
    captions.sort(key=lambda caption: caption[0][3])
    members: dict[int, list[Box]] = {index: [] for index in range(len(captions))}
    for picture in pictures:
        owner = next(
            (i for i, (box, _, _) in enumerate(captions) if box[3] >= picture[1]),
            len(captions) - 1,
        )
        if owner >= 0:
            members[owner].append(picture)
    figures = []
    for index, (_, number, caption) in enumerate(captions):
        if not members[index]:
            continue
        rect = pymupdf.Rect(members[index][0])
        for picture in members[index][1:]:
            rect |= pymupdf.Rect(picture)
        rect = (rect + (-2, -2, 2, 2)) & page.rect
        figures.append((number, (rect.x0, rect.y0, rect.x1, rect.y1), caption))
    regions = [pymupdf.Rect(box) for _, box, _ in figures]
    body = [
        text for box, text in texts if not any(pymupdf.Rect(box).intersects(r) for r in regions)
    ]
    return figures, body


def _inside(inner: Box, outer: Box, tolerance: float = 2.0) -> bool:
    return (
        inner[0] >= outer[0] - tolerance
        and inner[1] >= outer[1] - tolerance
        and inner[2] <= outer[2] + tolerance
        and inner[3] <= outer[3] + tolerance
    )


def _cited(text: str) -> set[int]:
    """The figure numbers a paragraph names: "figure 5", "figures 2 and 3", "figures 8-12"."""
    numbers: set[int] = set()
    for first, second in CITED.findall(text):
        numbers.add(int(first))
        if second:
            a, b = int(first), int(second)
            numbers.update(range(a, b + 1) if 0 < b - a < 10 else [b])
    return numbers
