"""Build the labelled routing set in evals/gold/routes/, the router's gold.

    experiments/routing/.venv/bin/python -I experiments/routing/build_dataset.py

Run commons_dl.py first: it downloads the Wikimedia Commons files this script reads. Everything
else comes from the drawings and reports in data/.

The set is deterministic (fixed seeds, fixed PDF metadata), so two builds give the same bytes.
The item files go to routes/items/<label>/, and routes/routes.jsonl gets one line per item:

    id          a stable name, such as d_ctc01_p1_r72
    label       the case the router must pick: drawing, photo or text, or "other" for a file
                that fits no case (a whole report, a page of text, a logo, a physics diagram)
    kind        pdf, image or text, or text+pdf / text+image for a message with an attachment
    file        the item's file, relative to routes/ (null for text)
    text        the user's message (null for an attachment alone)
    attachment  for a message with an attachment, the id of the item whose file it sends
    group       the drawing, report page or Commons file the item was made from
    source      nist, ntsb_<report>, commons or written
    variant     how the item was made, such as render_150, jpeg, photo or scan_pdf
    notes       how it was made, in words, with the licence and page of a Commons file
    unit        what a split keeps on one side: one NTSB report, or one NIST drawing with all
                its pages and copies, one Commons file or one written question
"""

from __future__ import annotations

import io
import json
import random
import shutil
from collections import Counter
from pathlib import Path

import cv2
import numpy as np
import pymupdf
from PIL import Image

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
DATA = REPO / "evals" / "gold" / "routes"
LABELS_FILE = DATA / "routes.jsonl"
ITEMS = DATA / "items"
COMMONS_DOWNLOADS = HERE / ".cache" / "commons"  # written by commons_dl.py, not committed
COMMONS_MANIFEST = DATA / "commons.json"
DRAWINGS = sorted((REPO / "data" / "drawings").glob("*.pdf"))
REPORTS = sorted((REPO / "data" / "reports").glob("*.pdf"))

FIELDS = (
    "id",
    "label",
    "kind",
    "file",
    "text",
    "attachment",
    "group",
    "source",
    "variant",
    "notes",
    "unit",
)
SEED = 20261101
RENDER_DPIS = [72, 100, 150, 200, 300]
# Two degradations per page, cycling through all six pairs so each one is used 15 times.
DEGRADATION_PAIRS = [
    ("jpeg", "photo"),
    ("rotate", "crop"),
    ("jpeg", "crop"),
    ("rotate", "photo"),
    ("jpeg", "rotate"),
    ("photo", "crop"),
]
# Embedded report images that are logos, not part photos: (report, xref).
LOGO_XREFS = {("24-013", 159), ("18-061", 677)}
# Pages saved as picture-only "scanned" PDFs: (index into DRAWINGS, page index).
SCAN_PAGES = [(0, 0), (2, 0), (5, 1), (7, 2), (9, 3), (10, 1)]
# Report photos saved as one-picture PDFs: (report, xref).
PHOTO_PDFS = [("16-006", 32), ("18-061", 201), ("18-061", 336), ("24-013", 17), ("24-013", 21)]
# The drawing put behind a cover and a notes sheet (FTC-06, three sheets), the sheet scanned with
# an OCR layer (FTC-07 page 1, the NIST sheet with the most text), and the report page scanned
# with and without one (18-061 page 5, a full page of prose).
PACKAGE_DRAWING = 5
OCR_SCAN_PAGE = (6, 0)
SCANNED_REPORT_PAGE = (1, 4)
PACKAGE_COVER = [
    "DRAWING PACKAGE",
    "PART NUMBER: FTC-06-1000",
    "TITLE: PMI TEST MODEL, MACHINED HOUSING",
    "CONTENTS: COVER SHEET, GENERAL NOTES, SHEETS 1 TO 3",
    "REVISION: C",
]
PACKAGE_NOTES = [
    "INTERPRET DIMENSIONS AND TOLERANCES PER ASME Y14.5-2009.",
    "ALL DIMENSIONS ARE IN MILLIMETERS UNLESS OTHERWISE SPECIFIED.",
    "MATERIAL: ALUMINUM ALLOY 6061-T6 PER ASTM B221.",
    "REMOVE ALL BURRS AND BREAK SHARP EDGES 0.2 TO 0.5 MM.",
    "SURFACE FINISH Ra 3.2 MICROMETERS MAXIMUM UNLESS OTHERWISE SPECIFIED.",
    "UNTOLERANCED DIMENSIONS PER ISO 2768-m.",
    "FINISH: CLEAR ANODIZE PER MIL-A-8625 TYPE II, CLASS 1, AFTER ALL MACHINING.",
    "MARK PART NUMBER AND REVISION WITH 3 MM CHARACTERS IN THE AREA SHOWN.",
    "INSPECT DATUM FEATURES A, B AND C BEFORE ANY OTHER FEATURE.",
    "CHECK ALL THREADED HOLES WITH GO AND NO-GO THREAD GAUGES.",
    "PROTECT MACHINED SURFACES FROM DAMAGE DURING HANDLING AND SHIPPING.",
    "NO CHANGE TO THIS DRAWING WITHOUT WRITTEN ENGINEERING APPROVAL.",
    "A FIRST ARTICLE INSPECTION REPORT IS REQUIRED WITH THE FIRST DELIVERY.",
    "PARTS MUST BE CLEAN AND FREE OF OIL, CHIPS AND MARKING INK ON DELIVERY.",
    "THE SOLID MODEL IS THE MASTER FOR ALL GEOMETRY NOT DIMENSIONED ON THE SHEETS.",
    "THIS PACKAGE IS COMPLETE ONLY WITH ALL SHEETS LISTED ON THE COVER.",
]
FIXED_METADATA = {"creationDate": "D:20261101000000", "modDate": "D:20261101000000"}

# Commons file name: what it shows.
COMMONS_PHOTOS = {
    "Al tensile test.jpg": "aluminium tensile specimens, ductile fracture",
    "Cast iron tensile test.JPG": "cast iron tensile specimens, brittle fracture",
    "Conchoidal.JPG": "conchoidal fracture of glassy rock",
    "Ductile Fracture Surface 6061-T6 Al SEM.png": "SEM image of a ductile aluminium fracture",
    "Eprouvette plate cassee facies.JPG": "broken flat test specimen",
    "Limescale-in-pipe.jpg": "cut pipe with scale deposit",
    "Pedalarm Bruch.jpg": "broken pedal arm fracture face",
    "Roman lock bolt. (FindID 1003766).jpg": "corroded copper alloy parts with scale bar",
    "Broken shaft and terminal from a copper alloy lock bolt (FindID 52550).jpg": (
        "broken corroded shaft with ruler"
    ),
    "Our broken vcr ~ part 3 ~ detail (712297).jpg": "inside of a broken VCR mechanism",
    "NDI; Exposing the cracks (5123803).jpg": "technician at a crack inspection station",
    "NDI; Exposing the cracks (5123808).jpg": "fluorescent penetrant crack inspection",
}
COMMONS_DRAWINGS = {
    "AbgewickeltesBlech01.jpg": "sheet metal flat pattern line drawing",
    "Ansichten2.jpg": "orthographic views of a block, German labels",
    "Air compressor, vertical, section (Rankin Kennedy, Modern Engines, Vol VI).jpg": (
        "engraved section drawing of a compressor"
    ),
    "Albertkoppel ritning.jpg": "scanned book page with coupling drawings and text",
    "Example of Steel Reinforcement Shop Drawing.jpg": "rebar shop drawing with schedules",
    "Werkstattzeichnung des Normalsegelapparats.jpg": "historic workshop drawing on aged paper",
    "2020-03-20 16 51 24-Autodesk Fusion 360.png": (
        "CAD sketch screenshot with dimensions, dark background"
    ),
}
COMMONS_DIAGRAM = ("Abmessungen.jpg", "physics diagram with coloured fill, not a part drawing")
# Short names that the 24-character rule in commons_slug() would get wrong.
COMMONS_SLUGS = {
    "Pedalarm Bruch.jpg": "pedalarm",
    # the two "NDI; Exposing the cracks" files share their first 24 characters
    "NDI; Exposing the cracks (5123808).jpg": "ndiexposingthecracks5123808",
}

TEXT_PROMPTS = [
    "What caused the left aileron cable to fail?",
    "Summarise the main findings of the materials lab reports.",
    "Which report talks about fatigue cracking in a wing spar?",
    "What is intergranular corrosion and how do I spot it?",
    "How should I inspect a control cable for broken wires?",
    "List the recommended actions after finding corrosion on a spar cap.",
    "What does beach marking on a fracture surface mean?",
    "Was there any evidence of overload in the 24-013 report?",
    "Explain the difference between ductile and brittle fracture.",
    "What alloy was the fractured fitting made of?",
    "how do i tell if a bolt failed from fatigue",
    "Give me the hardness values measured in the lab reports.",
    "What does GD&T position tolerance mean?",
    "Can you explain what datum A B C means on a drawing?",
    "What is a feature control frame?",
    "Which tolerance is tighter, 0.05 or +/-0.1?",
    "hi, what can you do?",
    "Is pitting corrosion dangerous for aluminium parts?",
    "What maintenance interval would have caught this crack earlier?",
    "Compare the failure modes across all three investigations.",
]
# (message, attachment item id). The messages numbered here point at the other case.
TEXT_PAIRS = [
    ("Can you check this drawing for me?", "d_ctc01_pdf"),
    ("What is wrong with this part?", "d_ftc06_pdf"),
    ("why did this crack?", "d_ctc02_p3_photo"),
    ("Here is the sheet from the supplier, page 2.", "d_ftc10_p2_r300"),
    ("Please explain this picture.", "d_ftc08_p3_crop"),
    ("Extract all the dimensions from this.", "p_18061_p13_x201"),
    ("Is this a fatigue fracture?", "p_16006_p09_x75"),
    ("Found this on the hangar floor, what happened?", "p_commons_pedalarm"),
    ("Here is the drawing of the fitting.", "p_24013_p05_x17"),
    ("What do you see?", "p_18061_p17_x337"),
]
MISLEADING_PAIRS = {2, 3, 5, 6, 9}


# ---------------------------------------------------------------------------
# Saving files


def save_png(img: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, optimize=True)


def save_jpeg(img: Image.Image, path: Path, quality: int, exif: bytes | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    options = {"quality": quality}
    if exif:
        options["exif"] = exif
    img.save(path, **options)


def save_pdf(doc: pymupdf.Document, path: Path) -> None:
    """Save with fixed dates and no new file id, so a rebuild gives the same bytes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.set_metadata(FIXED_METADATA)
    doc.save(path, deflate=True, no_new_id=True)


def copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(src, dst)


def render_page(page: pymupdf.Page, dpi: int) -> Image.Image:
    pix = page.get_pixmap(dpi=dpi, alpha=False)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def grey(img: Image.Image) -> Image.Image:
    """A grey copy kept in RGB, as a greyscale scanner would give."""
    return img.convert("L").convert("RGB")


def phone_exif() -> bytes:
    """Camera EXIF of the kind a phone writes. The item's notes say it is synthetic."""
    exif = Image.Exif()
    exif[271] = "Apple"  # Make
    exif[272] = "iPhone 13"  # Model
    exif[305] = "17.5.1"  # Software
    exif[306] = "2026:10:31 10:12:44"  # DateTime
    return exif.tobytes()


def picture_pdf(
    img: Image.Image, path: Path, quality: int = 70, ocr_text: str | None = None
) -> None:
    """A PDF of one picture, optionally with text as an invisible layer, as OCR software adds."""
    jpeg = io.BytesIO()
    img.convert("RGB").save(jpeg, "JPEG", quality=quality)
    doc = pymupdf.open()
    width, height = img.size
    points_per_pixel = 72 / 150  # the picture fills the page as a 150 dpi scan would
    page = doc.new_page(width=width * points_per_pixel, height=height * points_per_pixel)
    page.insert_image(page.rect, stream=jpeg.getvalue())
    if ocr_text:
        margin = (20, 20, -20, -20)
        # render_mode 3 writes the text without drawing it
        spare = page.insert_textbox(page.rect + margin, ocr_text, fontsize=4, render_mode=3)
        assert spare >= 0, "the OCR text did not fit on the page"
    save_pdf(doc, path)


def drawing_package(src: Path, path: Path) -> None:
    """A cover sheet and a general-notes sheet in front of a drawing's own vector sheets."""
    doc = pymupdf.open()
    width, height = 792, 612  # US letter, landscape
    frame = pymupdf.Rect(18, 18, width - 18, height - 18)
    cover = doc.new_page(width=width, height=height)
    cover.draw_rect(frame, width=1.5)
    cover.insert_text((60, 120), PACKAGE_COVER[0], fontsize=22)
    for row, line in enumerate(PACKAGE_COVER[1:]):
        cover.insert_text((60, 170 + 20 * row), line, fontsize=11)
    for row in range(5):  # an empty revision block
        y = height - 150 + 20 * row
        cover.draw_line((width - 330, y), (width - 40, y))
    notes = doc.new_page(width=width, height=height)
    notes.draw_rect(frame, width=1.5)
    notes.insert_text((40, 56), "GENERAL NOTES", fontsize=14)
    body = "\n".join(f"{number}. {note}" for number, note in enumerate(PACKAGE_NOTES, 1))
    spare = notes.insert_textbox(pymupdf.Rect(40, 72, width - 40, height - 40), body, fontsize=10)
    assert spare >= 0, "the notes did not fit on the page"
    with pymupdf.open(src) as sheets:
        doc.insert_pdf(sheets)
    save_pdf(doc, path)


# ---------------------------------------------------------------------------
# Degraded copies of a drawing page. Each takes the seeded random generator and returns the
# copy and a note on what was done.


def degrade_jpeg(img: Image.Image, rng: random.Random) -> tuple[Image.Image, str]:
    quality = rng.randint(12, 30)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality)
    return Image.open(io.BytesIO(buf.getvalue())).convert("RGB"), f"JPEG quality {quality}"


def degrade_rotate(img: Image.Image, rng: random.Random) -> tuple[Image.Image, str]:
    angle = rng.choice([-1, 1]) * rng.uniform(2, 7)
    out = img.rotate(angle, resample=Image.BICUBIC, expand=True, fillcolor=(235, 235, 235))
    return out, f"rotated {angle:.1f} degrees"


def degrade_photo(img: Image.Image, rng: random.Random) -> tuple[Image.Image, str]:
    """Make a render look like a phone photo of the printed sheet lying on a desk."""
    sheet = np.asarray(img).astype(np.float32)
    height, width = sheet.shape[:2]
    pad = int(0.12 * max(height, width))
    canvas_h, canvas_w = height + 2 * pad, width + 2 * pad

    def jitter(size: int) -> float:  # how far a corner moves inwards
        return rng.uniform(0.0, 0.07) * size

    corners = np.float32([[0, 0], [width, 0], [width, height], [0, height]])
    # each corner moves inwards by its own amount, so the sheet looks seen at an angle
    moved = np.float32(
        [
            [pad + jitter(width), pad + jitter(height)],
            [pad + width - jitter(width), pad + jitter(height)],
            [pad + width - jitter(width), pad + height - jitter(height)],
            [pad + jitter(width), pad + height - jitter(height)],
        ]
    )
    warp = cv2.getPerspectiveTransform(corners, moved)
    desk = np.array([rng.uniform(70, 120), rng.uniform(60, 100), rng.uniform(45, 80)], np.float32)
    warped = cv2.warpPerspective(
        sheet, warp, (canvas_w, canvas_h), borderMode=cv2.BORDER_CONSTANT, borderValue=desk.tolist()
    )
    # light falls off with the distance from a random point
    rows, cols = np.mgrid[0:canvas_h, 0:canvas_w].astype(np.float32)
    light_x, light_y = rng.uniform(0.2, 0.8) * canvas_w, rng.uniform(0.2, 0.8) * canvas_h
    distance = np.sqrt((cols - light_x) ** 2 + (rows - light_y) ** 2) / max(canvas_h, canvas_w)
    light = 1.0 - rng.uniform(0.35, 0.55) * distance
    warm_tint = np.array([1.0, rng.uniform(0.93, 0.98), rng.uniform(0.82, 0.92)], np.float32)
    out = warped * light[..., None] * warm_tint
    out = cv2.GaussianBlur(out, (0, 0), rng.uniform(0.8, 1.6))
    out += np.random.default_rng(rng.randint(0, 10**6)).normal(0, 5, out.shape)
    out = np.clip(out, 0, 255).astype(np.uint8)
    return Image.fromarray(out), "perspective warp, uneven light, warm tint, blur, noise"


def degrade_crop(img: Image.Image, rng: random.Random) -> tuple[Image.Image, str]:
    """Crop to one view: the largest blob of ink away from the border and the title block."""
    gray = np.asarray(img.convert("L"))
    height, width = gray.shape
    ink = (gray < 200).astype(np.uint8)
    border = int(0.04 * min(height, width))
    ink[:border] = 0
    ink[-border:] = 0
    ink[:, :border] = 0
    ink[:, -border:] = 0
    ink[int(0.72 * height) :, int(0.55 * width) :] = 0  # the title block corner
    # thicken the ink so the lines of one view join into one blob
    kernel = max(3, int(0.03 * min(height, width)))
    blobs = cv2.dilate(ink, np.ones((kernel, kernel), np.uint8))
    count, _, stats, _ = cv2.connectedComponentsWithStats(blobs)
    if count > 1:
        largest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))  # 0 is the background
        x, y, blob_w, blob_h = stats[largest, :4]
        if blob_w * blob_h < 0.6 * width * height:
            margin = int(0.03 * min(height, width))
            box = (
                max(0, x - margin),
                max(0, y - margin),
                min(width, x + blob_w + margin),
                min(height, y + blob_h + margin),
            )
            return img.crop(box), "crop to the largest view"
    # no single view stands out, so crop a random part of the sheet
    crop_w = int(width * rng.uniform(0.4, 0.55))
    crop_h = int(height * rng.uniform(0.45, 0.6))
    x0 = rng.randint(border, width - crop_w - border)
    y0 = rng.randint(border, height - crop_h - border)
    return img.crop((x0, y0, x0 + crop_w, y0 + crop_h)), "random crop (no single view found)"


DEGRADE = {
    "jpeg": degrade_jpeg,
    "rotate": degrade_rotate,
    "photo": degrade_photo,
    "crop": degrade_crop,
}


# ---------------------------------------------------------------------------
# Naming


def drawing_tag(pdf: Path) -> str:
    """ctc01 for nist_ctc_01_asme1_rd.pdf."""
    parts = pdf.stem.split("_")
    return f"{parts[1]}{parts[2]}"


def report_tag(pdf: Path) -> str:
    """16-006 for ntsb_16-006.pdf."""
    return pdf.stem.split("_")[1]


def commons_slug(name: str) -> str:
    """The first 24 letters and digits of a Commons file name, lower case."""
    if name in COMMONS_SLUGS:
        return COMMONS_SLUGS[name]
    return "".join(c for c in Path(name).stem.lower() if c.isalnum())[:24]


def is_mask(img: Image.Image) -> bool:
    """Callout arrow masks and inset frames are almost pure black and white with no texture.

    The real radiographs have at most 67% such pixels; the frames have 96% or more.
    """
    gray = np.asarray(img.convert("L"))
    extreme = np.mean((gray < 20) | (gray > 235))
    return extreme > 0.93 or len(np.unique(gray)) < 12


def embedded_image(doc: pymupdf.Document, xref: int) -> Image.Image:
    """A picture stored in a PDF, as RGB."""
    pix = pymupdf.Pixmap(doc, xref)
    if pix.n - pix.alpha >= 4:  # CMYK
        pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
    if pix.alpha:
        pix = pymupdf.Pixmap(pix, 0)
    return Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")


# ---------------------------------------------------------------------------
# The labelled set, one group of items at a time


class LabelledSet:
    def __init__(self) -> None:
        self.items: list[dict] = []
        self.rng = random.Random(SEED)
        self.commons = json.loads(COMMONS_MANIFEST.read_text())

    def add(self, *, file: Path | None, **fields) -> None:
        item = {"text": None, "attachment": None, "notes": "", **fields}
        item["file"] = str(file.relative_to(DATA)) if file else None
        source = item["source"]
        item["unit"] = source if source.startswith("ntsb_") else item["group"]
        self.items.append({name: item[name] for name in FIELDS})

    def by_id(self, item_id: str) -> dict:
        return next(it for it in self.items if it["id"] == item_id)

    def commons_credit(self, name: str) -> str:
        entry = self.commons[name]
        return f"{entry['licence']}; {entry['page']}"


def add_nist_drawings(s: LabelledSet) -> None:
    """Each NIST PDF as it is, one clean render of each page and two degraded copies."""
    page_count = 0  # over all drawings, to cycle the render dpi and the degradation pairs
    phone_photos = 0
    for pdf in DRAWINGS:
        tag = drawing_tag(pdf)
        dst = ITEMS / "drawing" / f"{tag}.pdf"
        copy_file(pdf, dst)
        common = {"label": "drawing", "group": tag, "source": "nist"}
        s.add(
            id=f"d_{tag}_pdf",
            kind="pdf",
            file=dst,
            variant="pdf",
            notes="original vector PDF",
            **common,
        )
        with pymupdf.open(pdf) as doc:
            for page_index, page in enumerate(doc):
                name = f"{tag}_p{page_index + 1}"
                dpi = RENDER_DPIS[page_count % len(RENDER_DPIS)]
                render = render_page(page, dpi)
                dst = ITEMS / "drawing" / f"{name}_r{dpi}.png"
                save_png(render, dst)
                s.add(
                    id=f"d_{name}_r{dpi}",
                    kind="image",
                    file=dst,
                    variant=f"render_{dpi}",
                    notes=f"clean render at {dpi} dpi",
                    **common,
                )
                at_150 = render if dpi == 150 else render_page(page, 150)
                for kind in DEGRADATION_PAIRS[page_count % len(DEGRADATION_PAIRS)]:
                    src = render_page(page, 200) if kind == "crop" else at_150
                    copy, how = DEGRADE[kind](src, s.rng)
                    if kind == "photo":
                        exif = phone_exif() if phone_photos % 2 == 0 else None  # every second
                        phone_photos += 1
                        dst = ITEMS / "drawing" / f"{name}_photo.jpg"
                        save_jpeg(copy, dst, 85, exif)
                        if exif:
                            how += "; synthetic phone EXIF (Apple iPhone 13)"
                    elif kind == "jpeg":
                        dst = ITEMS / "drawing" / f"{name}_jpeg.jpg"
                        copy.save(dst, quality=95)  # it already carries the low-quality artefacts
                    else:
                        dst = ITEMS / "drawing" / f"{name}_{kind}.png"
                        save_png(copy, dst)
                    s.add(
                        id=f"d_{name}_{kind}",
                        kind="image",
                        file=dst,
                        variant=kind,
                        notes=how,
                        **common,
                    )
                page_count += 1


def add_scanned_drawings(s: LabelledSet) -> None:
    """Drawing pages as picture-only PDFs: grey, slightly turned, no vector paths."""
    for drawing, page_index in SCAN_PAGES:
        pdf = DRAWINGS[drawing]
        tag = drawing_tag(pdf)
        with pymupdf.open(pdf) as doc:
            scan, how = degrade_rotate(grey(render_page(doc[page_index], 150)), s.rng)
        dst = ITEMS / "drawing" / f"{tag}_p{page_index + 1}_scan.pdf"
        picture_pdf(scan, dst, quality=60)
        s.add(
            id=f"d_{tag}_p{page_index + 1}_scanpdf",
            label="drawing",
            kind="pdf",
            file=dst,
            group=tag,
            source="nist",
            variant="scan_pdf",
            notes=f"raster-only PDF of a grey render, {how}",
        )


def add_commons_drawings(s: LabelledSet) -> None:
    """Drawings in other styles, to check that a classifier has not only learned the NIST sheets."""
    for name, shows in COMMONS_DRAWINGS.items():
        slug = commons_slug(name)
        dst = ITEMS / "drawing" / f"commons_{slug}.png"
        save_png(Image.open(COMMONS_DOWNLOADS / name).convert("RGB"), dst)
        s.add(
            id=f"d_commons_{slug}",
            label="drawing",
            kind="image",
            file=dst,
            group=f"commons_{slug}",
            source="commons",
            variant="commons",
            notes=f"{shows}; {s.commons_credit(name)}",
        )


def add_report_photos(s: LabelledSet) -> None:
    """Every picture of 200 by 200 pixels or more in the reports, minus the masks and logos.

    The two logos are kept as files that fit no case.
    """
    for pdf in REPORTS:
        report = report_tag(pdf)
        short = report.replace("-", "")
        with pymupdf.open(pdf) as doc:
            seen = set()
            for page in doc:
                for xref, _, width, height, *_ in page.get_images(full=True):
                    if xref in seen or width * height < 200 * 200:
                        continue
                    seen.add(xref)
                    img = embedded_image(doc, xref)
                    name = f"p_{short}_p{page.number + 1:02d}_x{xref}"
                    if (report, xref) in LOGO_XREFS:
                        dst = ITEMS / "other" / f"{name}.png"
                        save_png(img, dst)
                        s.add(
                            id=f"o_logo_{short}_x{xref}",
                            label="other",
                            kind="image",
                            file=dst,
                            group=f"ntsb_{report}",
                            source=f"ntsb_{report}",
                            variant="logo",
                            notes="letterhead or seal inside the report",
                        )
                        continue
                    if is_mask(img):
                        continue
                    dst = ITEMS / "photo" / f"{name}.jpg"
                    save_jpeg(img, dst, 90)
                    s.add(
                        id=name,
                        label="photo",
                        kind="image",
                        file=dst,
                        group=f"ntsb_{report}_p{page.number + 1:02d}",
                        source=f"ntsb_{report}",
                        variant="ntsb_figure",
                        notes=f"embedded image {width}x{height}",
                    )


def add_photo_pdfs(s: LabelledSet) -> None:
    """Five of the report photos, each saved as a PDF holding one picture."""
    for report, xref in PHOTO_PDFS:
        prefix = f"p_{report.replace('-', '')}_"
        photo = next(
            it for it in s.items if it["id"].startswith(prefix) and it["id"].endswith(f"_x{xref}")
        )
        dst = ITEMS / "photo" / f"{photo['id']}_pdf.pdf"
        picture_pdf(Image.open(DATA / photo["file"]), dst, quality=85)
        s.add(
            id=f"{photo['id']}_pdf",
            label="photo",
            kind="pdf",
            file=dst,
            group=photo["group"],
            source=photo["source"],
            variant="photo_pdf",
            notes="report photo as a raster-only PDF",
        )


def add_commons_photos(s: LabelledSet) -> None:
    """Photos of broken or corroded parts, shrunk to 2,048 pixels, camera EXIF kept."""
    for name, shows in COMMONS_PHOTOS.items():
        slug = commons_slug(name)
        original = Image.open(COMMONS_DOWNLOADS / name)
        exif = original.info.get("exif")
        photo = original.convert("RGB")
        photo.thumbnail((2048, 2048))
        dst = ITEMS / "photo" / f"commons_{slug}.jpg"
        save_jpeg(photo, dst, 90, exif)
        has_exif = "camera EXIF kept" if exif else "no EXIF"
        s.add(
            id=f"p_commons_{slug}",
            label="photo",
            kind="image",
            file=dst,
            group=f"commons_{slug}",
            source="commons",
            variant="commons",
            notes=f"{shows}; {has_exif}; {s.commons_credit(name)}",
        )


def add_files_that_fit_no_case(s: LabelledSet) -> None:
    """The whole reports, two report text pages as images and a physics diagram."""
    for pdf in REPORTS:
        report = report_tag(pdf)
        dst = ITEMS / "other" / pdf.name
        copy_file(pdf, dst)
        s.add(
            id=f"o_report_{report.replace('-', '')}_pdf",
            label="other",
            kind="pdf",
            file=dst,
            group=f"ntsb_{report}",
            source=f"ntsb_{report}",
            variant="report_pdf",
            notes="whole NTSB report; no case in the brief covers it",
        )
    for pdf, page_index in [(REPORTS[0], 1), (REPORTS[1], 2)]:
        report = report_tag(pdf)
        with pymupdf.open(pdf) as doc:
            page = render_page(doc[page_index], 110)
        dst = ITEMS / "other" / f"report_{report}_page{page_index + 1}.png"
        save_png(page, dst)
        s.add(
            id=f"o_report_{report.replace('-', '')}_page{page_index + 1}",
            label="other",
            kind="image",
            file=dst,
            group=f"ntsb_{report}",
            source=f"ntsb_{report}",
            variant="report_page",
            notes="text page of a report as an image",
        )
    name, shows = COMMONS_DIAGRAM
    dst = ITEMS / "other" / "commons_abmessungen.png"
    save_png(Image.open(COMMONS_DOWNLOADS / name).convert("RGB"), dst)
    s.add(
        id="o_commons_abmessungen",
        label="other",
        kind="image",
        file=dst,
        group="commons_abmessungen",
        source="commons",
        variant="diagram",
        notes=f"{shows}; {s.commons_credit(name)}",
    )


def add_archive_pdfs(s: LabelledSet) -> None:
    """PDFs a customer's archive holds that the groups above miss.

    A drawing package whose cover and notes sheets come before the drawing sheets, a scanned
    drawing with an OCR text layer, and a scanned report page with and without one.
    """
    pdf = DRAWINGS[PACKAGE_DRAWING]
    tag = drawing_tag(pdf)
    dst = ITEMS / "drawing" / f"{tag}_package.pdf"
    drawing_package(pdf, dst)
    s.add(
        id=f"d_{tag}_package_pdf",
        label="drawing",
        kind="pdf",
        file=dst,
        group=tag,
        source="nist",
        variant="package_pdf",
        notes="cover sheet and a general-notes sheet in front of the original vector sheets",
    )

    drawing, page_index = OCR_SCAN_PAGE
    tag = drawing_tag(DRAWINGS[drawing])
    with pymupdf.open(DRAWINGS[drawing]) as doc:
        scan, text = grey(render_page(doc[page_index], 150)), doc[page_index].get_text()
    dst = ITEMS / "drawing" / f"{tag}_p{page_index + 1}_ocrscan.pdf"
    picture_pdf(scan, dst, quality=60, ocr_text=text)
    s.add(
        id=f"d_{tag}_p{page_index + 1}_ocrscan",
        label="drawing",
        kind="pdf",
        file=dst,
        group=tag,
        source="nist",
        variant="ocr_scan_pdf",
        notes=f"grey 150 dpi scan with the sheet's own text ({len(text.strip())} characters) "
        "as an invisible OCR layer",
    )

    report_index, page_index = SCANNED_REPORT_PAGE
    report = report_tag(REPORTS[report_index])
    with pymupdf.open(REPORTS[report_index]) as doc:
        scan, text = grey(render_page(doc[page_index], 150)), doc[page_index].get_text()
    for variant, ocr_text, layer in (
        ("report_scan_pdf", None, "no text layer"),
        ("report_ocr_scan_pdf", text, f"its text ({len(text.strip())} characters) as an OCR layer"),
    ):
        suffix = "ocrscan" if ocr_text else "scan"
        dst = ITEMS / "other" / f"report_{report}_page{page_index + 1}_{suffix}.pdf"
        picture_pdf(scan, dst, quality=60, ocr_text=ocr_text)
        s.add(
            id=f"o_report_{report.replace('-', '')}_page{page_index + 1}_{suffix}",
            label="other",
            kind="pdf",
            file=dst,
            group=f"ntsb_{report}",
            source=f"ntsb_{report}",
            variant=variant,
            notes=f"report text page scanned in grey at 150 dpi, {layer}",
        )


def add_text_items(s: LabelledSet) -> None:
    """Questions with no attachment, and messages sent with a file from the set."""
    for number, question in enumerate(TEXT_PROMPTS, 1):
        s.add(
            id=f"t_{number:02d}",
            label="text",
            kind="text",
            file=None,
            text=question,
            group=f"text_{number:02d}",
            source="written",
            variant="text_only",
        )
    for number, (message, attachment_id) in enumerate(TEXT_PAIRS, 1):
        attachment = s.by_id(attachment_id)
        notes = "text points at the other case" if number in MISLEADING_PAIRS else ""
        s.add(
            id=f"tp_{number:02d}",
            label=attachment["label"],
            kind=f"text+{attachment['kind']}",
            file=DATA / attachment["file"],
            text=message,
            attachment=attachment_id,
            group=attachment["group"],
            source=attachment["source"],
            variant="text_pair",
            notes=notes,
        )


def build() -> list[dict]:
    """Every item, in a fixed order: the random generator is shared, so the order matters."""
    if ITEMS.exists():
        shutil.rmtree(ITEMS)
    s = LabelledSet()
    add_nist_drawings(s)
    add_scanned_drawings(s)
    add_commons_drawings(s)
    add_report_photos(s)
    add_photo_pdfs(s)
    add_commons_photos(s)
    add_files_that_fit_no_case(s)
    add_archive_pdfs(s)
    add_text_items(s)
    return s.items


def main() -> None:
    items = build()
    ids = Counter(it["id"] for it in items)
    duplicates = sorted(i for i, n in ids.items() if n > 1)
    assert not duplicates, f"duplicate item ids: {duplicates}"
    with LABELS_FILE.open("w") as fh:
        for it in items:
            fh.write(json.dumps(it, ensure_ascii=False) + "\n")
    print(len(items), "items")
    print(Counter(it["label"] for it in items))
    print(Counter((it["label"], it["variant"]) for it in items))


if __name__ == "__main__":
    main()
