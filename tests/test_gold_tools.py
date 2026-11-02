import copy
from decimal import Decimal as D

import pytest

import gold_schema
import grid
import limits
import overlay
from common import load_gold, open_drawing

STEM = "nist_ctc_01_asme1_rd"


def record(raw, style, callout="dimension"):
    return {"raw": raw, "tolerance_style": style, "callout": callout}


@pytest.mark.parametrize(
    "raw, style, value, bounds",
    [
        ("⌀25 ±0.15", "plus_minus", D("25"), (D("24.85"), D("25.15"))),
        ("60° ±0.5°", "plus_minus", D("60"), (D("59.5"), D("60.5"))),
        ("⌀20 +0.05/-0.10", "bilateral_unequal", D("20"), (D("19.90"), D("20.05"))),
        ("⌀35 0/-0.2", "unilateral", D("35"), (D("34.8"), D("35"))),
        ("⌀35 +0.2/0", "unilateral", D("35"), (D("35"), D("35.2"))),
        ("⌀34.8 - 35.2", "limits", [D("34.8"), D("35.2")], (D("34.8"), D("35.2"))),
        ("⌀35.2/34.8", "limits", [D("34.8"), D("35.2")], (D("34.8"), D("35.2"))),
        ("2X ⌀.438 ±.005", "plus_minus", D(".438"), (D(".433"), D(".443"))),
        ("R.012 - .022", "limits", [D(".012"), D(".022")], (D(".012"), D(".022"))),
        ("(SR.500)", "reference", D(".500"), None),
        ("30X ⌀14", "basic", D("14"), None),
    ],
)
def test_derive_dimension(raw, style, value, bounds):
    assert limits.derive(record(raw, style)) == (value, bounds)


@pytest.mark.parametrize(
    "raw, zone",
    [
        ("⌓ 1.25 | A | B | C (A ↔ B)", D("1.25")),
        ("⌖ ⌀.025Ⓜ | C | A | B", D(".025")),
        ("⌖ S⌀.025 | D | B | C", D(".025")),
        ("⌖ ⌀0.75Ⓟ50 | A | B | C", D("0.75")),
        ("▱ .005 / .25 X .25", D(".005")),
    ],
)
def test_derive_frame_zone(raw, zone):
    assert limits.derive(record(raw, "geometric_zone", "feature_control_frame")) == (
        zone,
        (D(0), zone),
    )


def test_untoleranced_ratio_has_nothing_to_derive():
    assert limits.derive(record("2X ⌲ 1.00 : 3.00", "none")) is None


def test_ctc01_limits_match_raw():
    for v in load_gold(STEM)["values"]:
        if v["callout"] in ("dimension", "feature_control_frame"):
            assert limits.check(v) is None, v["id"]


def test_wrong_stored_limit_is_reported():
    v = copy.deepcopy(next(v for v in load_gold(STEM)["values"] if v["raw"] == "⌀20 +0.05/-0.10"))
    v["limits"]["lower"] = 19.95
    assert limits.check(v).startswith("limits")


def test_unparseable_toleranced_raw_is_reported():
    assert limits.check(
        {**record("⌀20 sort of", "plus_minus"), "value": 20, "limits": None}
    ).startswith("cannot")


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
