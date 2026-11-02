from io import BytesIO

import pytest
from PIL import Image

from resourcly.adapters.report_figures import cut_report, render_figure
from resourcly.bootstrap import PROJECT_ROOT

REPORTS = PROJECT_ROOT / "data" / "reports"


@pytest.fixture(scope="module")
def spars():
    return cut_report(REPORTS / "ntsb_18-061.pdf")


def test_every_report_figure_is_cut_with_its_caption_and_page() -> None:
    counts = {pdf.name: len(cut_report(pdf).figures) for pdf in sorted(REPORTS.glob("*.pdf"))}

    assert counts == {"ntsb_16-006.pdf": 12, "ntsb_18-061.pdf": 29, "ntsb_24-013.pdf": 5}


def test_a_figure_keeps_its_caption_page_and_box(spars) -> None:
    fig05 = next(figure for figure in spars.figures if figure.figure == "18-061/fig05")

    assert (fig05.report, fig05.number, fig05.page) == ("18-061", 5, 13)
    assert fig05.caption.startswith("Figure 5. Closer views of the fracture surfaces")
    left, top, right, bottom = fig05.bbox
    assert 0 <= left < right and 0 <= top < bottom


def test_a_figure_keeps_the_paragraphs_that_cite_it(spars) -> None:
    fig05 = next(figure for figure in spars.figures if figure.figure == "18-061/fig05")

    assert [passage.source for passage in fig05.citing] == ["18-061 p2", "18-061 p2", "18-061 p3"]
    assert fig05.citing[1].text.startswith("Unlabeled arrows in figure 5")
    assert fig05.citing[2].text.startswith("In the doublers, fatigue origins were noted")


def test_a_paragraph_cut_by_a_page_break_is_joined_and_cited_by_its_first_page(spars) -> None:
    [joined] = [p for p in spars.paragraphs if p.text.startswith("Unlabeled arrows in figure 5")]

    assert joined.page == 2
    assert joined.text.endswith("near the upper aft side of the lower spar cap as shown.")
    assert not any(p.text.startswith("the aft side of hole LD-1") for p in spars.paragraphs)


def test_page_headers_and_signatures_are_not_paragraphs(spars) -> None:
    texts = [paragraph.text for paragraph in spars.paragraphs]

    assert not any("Report No." in text or "Page No." in text for text in texts)
    assert not any(text.startswith("Matthew R. Fox") for text in texts)


def test_the_closing_paragraphs_are_the_last_of_the_body_before_the_figures() -> None:
    throttle_arm = cut_report(REPORTS / "ntsb_24-013.pdf")

    assert [passage.source for passage in throttle_arm.closing] == ["24-013 p3", "24-013 p3"]
    assert throttle_arm.closing[-1].text == (
        "The fracture to the fuel servo throttle arm is consistent with bending overstress."
    )


def test_the_report_says_what_was_examined(spars) -> None:
    assert spars.report == "18-061"
    assert spars.vehicle == "Piper PA-28R-201, N106ER"
    assert spars.components.startswith("Center wing box assembly")


def test_a_figure_renders_as_a_png_of_its_box(spars) -> None:
    fig05 = next(figure for figure in spars.figures if figure.figure == "18-061/fig05")

    image = Image.open(
        BytesIO(render_figure(REPORTS / "ntsb_18-061.pdf", fig05.page, fig05.bbox, dpi=72))
    )

    left, top, right, bottom = fig05.bbox
    assert image.format == "PNG"
    assert image.size == pytest.approx((right - left, bottom - top), abs=2)
