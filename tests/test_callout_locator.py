import json

import pymupdf
import pytest

from resourcly.adapters.callout_locator import (
    Frame,
    PagePaths,
    Rect,
    annotation_colour,
    group_callouts,
    locate,
)
from resourcly.bootstrap import PROJECT_ROOT
from tests.conftest import CTC01

DRAWINGS = PROJECT_ROOT / "data" / "drawings"
GOLD = PROJECT_ROOT / "evals" / "gold"


def _gold_boxes(drawing: str, page: int, callout: str) -> list[pymupdf.Rect]:
    values = json.loads((GOLD / "drawings" / f"{drawing}.json").read_text())["values"]
    return [
        pymupdf.Rect(v["bbox"]) for v in values if v["page"] == page and v["callout"] == callout
    ]


def _fraction(callout, page: pymupdf.Page) -> pymupdf.Rect:
    w, h = page.rect.width, page.rect.height
    box = callout.box
    return pymupdf.Rect(box.x0 / w, box.y0 / h, box.x1 / w, box.y1 / h)


@pytest.mark.parametrize(
    ("drawing", "page_number", "frames"),
    [
        (CTC01, 1, 6 + 3),
        ("nist_ctc_03_asme1_rc", 1, 13 + 6),
        ("nist_ftc_06_asme1_rd", 1, 10 + 3),
        ("nist_ftc_06_asme1_rd", 3, 6),  # 8 frames in the gold, two of them composite
    ],
)
def test_each_frame_and_datum_box_is_one_callout(drawing, page_number, frames) -> None:
    with pymupdf.open(DRAWINGS / f"{drawing}.pdf") as pdf:
        page = pdf[page_number - 1]
        boxes = [_fraction(c, page) for c in locate(page) if c.framed]

    assert len(boxes) == frames
    for gold in _gold_boxes(drawing, page_number, "feature_control_frame"):
        centre = (gold.tl + gold.br) / 2
        assert any(box.contains(centre) for box in boxes), f"no callout holds the frame at {gold}"


def test_finds_callouts_written_as_text() -> None:
    with pymupdf.open(DRAWINGS / "nist_ftc_07_asme1_rd.pdf") as pdf:
        page = pdf[1]
        boxes = [_fraction(c, page) for c in locate(page)]
    for gold in _gold_boxes("nist_ftc_07_asme1_rd", 2, "dimension"):
        assert any(not (box & gold).is_empty for box in boxes)


def test_the_annotation_colour_is_the_one_with_the_most_letters() -> None:
    with pymupdf.open(DRAWINGS / f"{CTC01}.pdf") as pdf:
        assert annotation_colour(pdf[0].get_drawings()) == (0.0, 0.0, 1.0)


def test_a_slanted_frame_owns_the_letters_inside_it() -> None:
    frame = Frame(((0, 0), (40, 10), (40, 20), (0, 10)))
    inside = Rect(18, 8, 22, 12)
    outside = Rect(2, 14, 4, 16)  # within the bounding box but below the slanted bottom edge
    callouts = group_callouts(PagePaths([inside, outside], [frame], 4.0), reach=0.1)

    assert [(c.framed, c.letters) for c in callouts] == [(True, 1)]


def test_a_frame_inside_a_frame_belongs_to_the_outer_one() -> None:
    outer = Frame(((0, 0), (60, 0), (60, 20), (0, 20)))
    symbol = Frame(((2, 2), (16, 2), (16, 18), (2, 18)))
    callouts = group_callouts(PagePaths([], [outer, symbol], 4.0))

    assert [c.box for c in callouts] == [Rect(0, 0, 60, 20)]


def test_lone_letters_are_dropped_and_close_letters_grouped() -> None:
    letters = [Rect(0, 0, 4, 4), Rect(5, 0, 9, 4), Rect(100, 100, 104, 104)]
    callouts = group_callouts(PagePaths(letters, [], 4.0))

    assert [(c.box, c.letters) for c in callouts] == [(Rect(0, 0, 9, 4), 2)]


def _word(x: float, y: float, n: int, dx: float = 5.0, dy: float = 0.0) -> list[Rect]:
    return [Rect(x + i * dx, y + i * dy, x + i * dx + 4, y + i * dy + 4) for i in range(n)]


def test_text_on_one_line_split_by_a_wide_gap_is_one_callout() -> None:
    letters = _word(0, 0, 4, dx=5, dy=-2.9) + _word(30, -17.4, 4, dx=5, dy=-2.9)  # a 30° line
    callouts = group_callouts(PagePaths(letters, [], 4.0))

    assert [c.letters for c in callouts] == [8]


def test_stacked_lines_of_text_stay_apart() -> None:
    letters = _word(0, 0, 5) + _word(0, 14, 5)
    callouts = group_callouts(PagePaths(letters, [], 4.0))

    assert [c.letters for c in callouts] == [5, 5]
