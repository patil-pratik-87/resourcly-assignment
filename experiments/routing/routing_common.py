"""Shared code for the routing experiments: the labelled set, page images and the rule features.

The notebook (routing.ipynb, built from routing.py) and run_models.py import this module.
Everything here runs offline on the CPU; the image models are loaded in the notebook, so each
approach reads top to bottom there.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import pymupdf
from PIL import Image

HERE = Path(__file__).resolve().parent
DATA = HERE.parents[1] / "evals" / "gold" / "routes"  # routes.jsonl and the files it names
RESULTS = HERE / "results"  # every measured number, committed
CACHE = HERE / ".cache"  # the Hugging Face cache and model input images, not committed

LABELS = ("drawing", "photo", "text")


def load_items() -> list[dict]:
    """Every labelled request, in the order of routes.jsonl."""
    with (DATA / "routes.jsonl").open() as fh:
        return [json.loads(line) for line in fh]


def item_path(item: dict) -> Path | None:
    return DATA / item["file"] if item.get("file") else None


def render_pdf_page(path: Path, page: int = 0, max_side: int = 1024) -> Image.Image:
    with pymupdf.open(path) as doc:
        pdf_page = doc[page]
        zoom = max_side / max(pdf_page.rect.width, pdf_page.rect.height)
        pix = pdf_page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
        return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def attachment_image(item: dict, max_side: int = 1024) -> Image.Image | None:
    """The picture a model sees for an item: the image, or page 1 of a PDF. None for text."""
    path = item_path(item)
    if path is None:
        return None
    if path.suffix.lower() == ".pdf":
        return render_pdf_page(path, 0, max_side)
    img = Image.open(path).convert("RGB")
    if max(img.size) > max_side:
        img.thumbnail((max_side, max_side), Image.BICUBIC)
    return img


# ---------------------------------------------------------------------------
# Approach A: rules on the file's structure and its pixels


TITLE_WORDS = re.compile(
    r"\b(scale|sheet|dwg|drawn|checked|tolerances?|dimensions?|unless otherwise|rev\b|revision|"
    r"third angle|first angle|datum|material|finish|part no|title)\b",
    re.I,
)


@dataclass
class PdfFeatures:
    pages: int
    vector_paths: int  # on page 1
    chars: int  # characters of text on page 1
    image_cover: float  # share of page 1 under pictures
    landscape: bool
    title_words: int  # title block words on page 1, such as "scale" or "drawn"
    max_chars_first10: int  # the most text on any of the first 10 pages
    pages_first10: list  # (vector paths, characters, picture cover) for each of the first 10


def page_layout(page: pymupdf.Page) -> tuple[int, int, float]:
    """A page's vector paths, characters of text and share of its area under pictures."""
    area = page.rect.width * page.rect.height
    cover = 0.0
    # get_image_info() gives the same boxes as get_image_rects() on every page here, at about
    # 0.3 ms instead of 20 to 40 ms for a page that is one picture
    for info in page.get_image_info():
        # image boxes are in unrotated page space, page.rect in the rotated view
        # (the NIST sheets carry /Rotate 270)
        box = (pymupdf.Rect(info["bbox"]) * page.rotation_matrix) & page.rect
        cover += max(0.0, box.width) * max(0.0, box.height)
    return len(page.get_cdrawings()), len(page.get_text().strip()), min(1.0, cover / area)


def pdf_features(path: Path) -> PdfFeatures:
    with pymupdf.open(path) as doc:
        first10 = [page_layout(doc[i]) for i in range(min(10, doc.page_count))]
        first = doc[0]
        return PdfFeatures(
            pages=doc.page_count,
            vector_paths=first10[0][0],
            chars=first10[0][1],
            image_cover=first10[0][2],
            landscape=first.rect.width > first.rect.height,
            title_words=len(TITLE_WORDS.findall(first.get_text())),
            max_chars_first10=max(chars for _, chars, _ in first10),
            pages_first10=first10,
        )


def largest_pdf_image(path: Path) -> Image.Image:
    """The largest picture on page 1 of a PDF, as RGB."""
    with pymupdf.open(path) as doc:
        page = doc[0]
        xref = max(page.get_images(full=True), key=lambda im: im[2] * im[3])[0]
        pix = pymupdf.Pixmap(doc, xref)
        if pix.n - pix.alpha >= 4:  # CMYK
            pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
        if pix.alpha:
            pix = pymupdf.Pixmap(pix, 0)
        mode = "L" if pix.n == 1 else "RGB"
        return Image.frombytes(mode, (pix.width, pix.height), pix.samples).convert("RGB")


@dataclass
class ImageFeatures:
    camera_exif: bool  # the file names a camera make or model
    white_frac: float  # share of near-white pixels (paper)
    sat_mean: float  # mean colour saturation
    top8_share: float  # share of pixels in the 8 most common colours
    flat_frac: float  # share of pixels with no texture (paper and solid fills)
    edge_density: float  # share of pixels on an edge
    straight_ratio: float  # share of edge pixels on a straight line


def camera_exif(path: Path | None) -> bool:
    if path is None or path.suffix.lower() == ".pdf":
        return False
    try:
        exif = Image.open(path).getexif()
    except Exception:
        return False
    return bool(exif.get(271) or exif.get(272))  # Make or Model


def straight_edge_ratio(edges: np.ndarray, edge_pixels: int, short_side: int) -> float:
    """The share of edge pixels that lie on a straight line segment (drawings have many)."""
    if not edge_pixels:
        return 0.0
    min_length = max(15, int(0.04 * short_side))
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, 40, minLineLength=min_length, maxLineGap=3)
    on_line = np.zeros_like(edges)
    if lines is not None:
        for x1, y1, x2, y2 in lines.reshape(-1, 4):
            cv2.line(on_line, (int(x1), int(y1)), (int(x2), int(y2)), 255, 3)
    return float(np.sum((edges > 0) & (on_line > 0)) / edge_pixels)


def image_features(img: Image.Image, exif: bool = False, side: int = 800) -> ImageFeatures:
    img = img.convert("RGB")
    if max(img.size) > side:
        img = img.copy()
        img.thumbnail((side, side), Image.BICUBIC)
    rgb = np.asarray(img)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    # colours quantised to 16 levels per channel, so each pixel is one of 4,096 colour codes
    levels = (rgb >> 4).reshape(-1, 3).astype(np.int32)
    codes = levels[:, 0] * 256 + levels[:, 1] * 16 + levels[:, 2]
    counts = np.bincount(codes, minlength=4096)
    laplacian = cv2.Laplacian(gray, cv2.CV_32F, ksize=3)
    edges = cv2.Canny(gray, 60, 160)
    edge_pixels = int(edges.sum() // 255)
    return ImageFeatures(
        camera_exif=exif,
        white_frac=float(np.mean(rgb.min(axis=2) > 225)),
        sat_mean=float(hsv[..., 1].mean() / 255),
        top8_share=float(np.sort(counts)[-8:].sum() / codes.size),
        flat_frac=float(np.mean(np.abs(laplacian) < 4)),
        edge_density=edge_pixels / edges.size,
        straight_ratio=straight_edge_ratio(edges, edge_pixels, min(gray.shape)),
    )


@dataclass
class RuleThresholds:
    """Cut points for the rules. The notebook fits the four image ones on one half of the set."""

    use_exif: bool = True
    drawing_white: float = 0.45  # at least this much near-white paper
    drawing_flat: float = 0.80  # and mostly flat, untextured pixels
    photo_white: float = 0.15  # at most this much near-white
    photo_flat: float = 0.60  # and mostly textured pixels
    pdf_vector_paths: int = 300  # a page with this many paths and little picture is a CAD sheet
    pdf_prose_page_chars: int = 1000  # a page with this much text is a page of prose
    full_page_picture: float = 0.9  # a page this much under a picture is judged by the picture


def pdf_page_kinds(pages: list, t: RuleThresholds) -> tuple[int, int]:
    """How many of the first ten pages are CAD sheets, and how many are pages of prose.

    A page that is one big picture (a scan, even with an OCR text layer) counts as neither, so
    its text never makes the PDF a document; the probe judges the picture instead.
    """
    sheets = prose = 0
    for paths, chars, cover in pages:
        if paths >= t.pdf_vector_paths and cover < 0.2:
            sheets += 1
        elif chars >= t.pdf_prose_page_chars and cover < t.full_page_picture:
            prose += 1
    return sheets, prose


def rule_features(item: dict) -> dict:
    """Every signal approach A looks at, computed once per item."""
    path = item_path(item)
    if path is None:
        return {"kind": "text"}
    if path.suffix.lower() == ".pdf":
        pdf = pdf_features(path)
        features = {"kind": "pdf", **{f"pdf_{k}": v for k, v in pdf.__dict__.items()}}
        if pdf.image_cover >= 0.5:  # a page that is mostly one picture: judge the picture too
            features.update(image_features(largest_pdf_image(path), False).__dict__)
        return features
    image = image_features(Image.open(path), camera_exif(path))
    return {"kind": "image", **image.__dict__}


def plural(count: int, word: str) -> str:
    return f"{count} {word}{'s' * (count != 1)}"


def decide_rules(f: dict, t: RuleThresholds) -> tuple[str, str]:
    """Approach A on precomputed features f. Returns (decision, reason).

    The decision is drawing, photo, text, document (a prose PDF, which no case in the brief
    covers) or undecided.
    """
    if f["kind"] == "text":
        return "text", "no attachment"
    prefix = ""
    if f["kind"] == "pdf":
        if f["pdf_vector_paths"] >= t.pdf_vector_paths and f["pdf_image_cover"] < 0.2:
            return "drawing", f"vector PDF, {f['pdf_vector_paths']} paths"
        # A drawing package (cover and notes sheets in front of the CAD sheets) is a drawing,
        # and a report with a vector chart is a document, so the page kinds are counted.
        sheets, prose = pdf_page_kinds(f["pdf_pages_first10"], t)
        kinds = f"{plural(sheets, 'CAD sheet')} and {plural(prose, 'prose page')} in the first ten"
        if sheets and sheets >= prose:
            return "drawing", f"drawing package, {kinds}"
        if f["pdf_image_cover"] < 0.5:
            if prose:
                return "document", f"prose PDF, {kinds}"
            return "undecided", "PDF with few vectors and no full-page image"
        prefix = "raster PDF: "
    if t.use_exif and f["camera_exif"]:
        return "photo", prefix + "camera EXIF"
    why = f"white {f['white_frac']:.2f}, flat {f['flat_frac']:.2f}"
    if f["white_frac"] >= t.drawing_white and f["flat_frac"] >= t.drawing_flat:
        return "drawing", prefix + why
    if f["white_frac"] <= t.photo_white and f["flat_frac"] <= t.photo_flat:
        return "photo", prefix + why
    return "undecided", prefix + why


# ---------------------------------------------------------------------------
# Measurement helpers


class Timer:
    """with Timer() as t: ...  then t.ms is the time the block took."""

    def __enter__(self):
        self.start = time.perf_counter()
        return self

    def __exit__(self, *exc):
        self.ms = (time.perf_counter() - self.start) * 1000


def rss_mb() -> float:
    """This process's resident memory in MB."""
    import psutil

    return psutil.Process(os.getpid()).memory_info().rss / 1e6


def confusion(y_true: list[str], y_pred: list[str], rows=LABELS, cols=None) -> dict:
    """{true label: {predicted label: count}}, for the true labels in rows."""
    cols = cols or sorted(set(y_pred) | set(rows), key=lambda c: (c not in rows, c))
    matrix = {r: {c: 0 for c in cols} for r in rows}
    for truth, pred in zip(y_true, y_pred, strict=True):
        if truth in matrix:
            matrix[truth][pred] = matrix[truth].get(pred, 0) + 1
    return matrix


def save_json(name: str, obj) -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / name).write_text(json.dumps(obj, indent=1, ensure_ascii=False, default=float))


def load_json(name: str):
    path = RESULTS / name
    return json.loads(path.read_text()) if path.exists() else None
