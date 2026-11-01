import pytest

import gold_schema
import grid
import overlay
from common import load_gold, open_drawing

STEM = "nist_ctc_01_asme1_rd"


@pytest.mark.parametrize(
    "render",
    [
        lambda page: overlay.render_overlay(page, load_gold(STEM)["values"], dpi=50),
        lambda page: grid.render_grid(page, (0, 0, 1, 1), dpi=50, step=0.1),
    ],
)
def test_renders_use_the_displayed_landscape_page(render):
    # The PDFs are stored portrait with a 270 degree rotation; bboxes refer to the landscape view.
    page = open_drawing(STEM)[0]
    pix = render(page)
    assert pix.width > pix.height
    assert abs(pix.width / pix.height - page.rect.width / page.rect.height) < 0.01


def test_the_committed_gold_schema_is_the_one_the_models_generate():
    committed = gold_schema.PATH.read_text(encoding="utf-8")

    assert committed == gold_schema.render(), (
        "evals/gold/schema.json is stale; run uv run python scripts/gold_tools/gold_schema.py"
    )
