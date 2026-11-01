import copy
import json

import pytest

from resourcly.bootstrap import PROJECT_ROOT
from resourcly.evals import gold_rules as rules

CTC01 = json.loads(
    (PROJECT_ROOT / "evals" / "gold" / "drawings" / "nist_ctc_01_asme1_rd.json").read_text()
)


@pytest.fixture
def doc():
    return copy.deepcopy(CTC01)


def value(doc, raw):
    return next(v for v in doc["values"] if v["raw"] == raw)


def test_ctc01_is_clean(doc):
    assert rules.validate(doc) == ([], [])


# rules beyond the models; the models already tie kind to callout and a limit dimension to a pair


def test_a_frame_is_a_geometric_zone(doc):
    value(doc, "▱ 0.2")["tolerance_style"] = "plus_minus"
    errors, _ = rules.validate(doc)
    assert any("a feature_control_frame has tolerance_style geometric_zone" in e for e in errors)


def test_geometric_zone_needs_a_number_and_does_not_crash(doc):
    value(doc, "▱ 0.2")["value"] = None
    errors, _ = rules.validate(doc)
    assert any("geometric_zone value must be a number" in e for e in errors)


def test_toleranced_dimension_needs_limits(doc):
    value(doc, "⌀25 ±0.15")["limits"] = None
    errors, _ = rules.validate(doc)
    assert any("plus_minus value needs limits" in e for e in errors)


def test_datum_symbol_must_not_carry_limits(doc):
    value(doc, "A")["limits"] = {"lower": 0, "upper": 1}
    errors, _ = rules.validate(doc)
    assert any("none value takes no limits" in e for e in errors)


def test_meaning_and_description_must_not_be_empty(doc):
    value(doc, "A")["meaning"] = ""
    doc["features"][0]["description"] = ""
    errors, _ = rules.validate(doc)
    assert any(e.endswith(": meaning must not be empty") for e in errors)
    assert any(e.endswith(": description must not be empty") for e in errors)


def test_a_document_lists_title_block_features_and_values(doc):
    del doc["features"]
    errors, _ = rules.validate(doc)
    assert any("document keys" in e for e in errors)


# ids, references, pages and order


def test_duplicate_value_id(doc):
    doc["values"][1]["id"] = doc["values"][0]["id"]
    errors, _ = rules.validate(doc)
    assert f"duplicate value id {doc['values'][0]['id']}" in errors


def test_unresolved_feature_id(doc):
    value(doc, "⌀25 ±0.15")["feature_id"] = "nope"
    errors, _ = rules.validate(doc)
    assert any("feature_id nope does not resolve" in e for e in errors)


def test_null_feature_id_only_for_title_block(doc):
    value(doc, "⌀25 ±0.15")["feature_id"] = None
    errors, _ = rules.validate(doc)
    assert any("feature_id is null but callout is dimension" in e for e in errors)


def test_page_beyond_page_count(doc):
    value(doc, "⌀25 ±0.15")["page"] = 2
    errors, _ = rules.validate(doc)
    assert any("beyond page_count" in e for e in errors)


def test_inverted_bbox(doc):
    v = value(doc, "⌀25 ±0.15")
    v["bbox"] = [v["bbox"][2], v["bbox"][1], v["bbox"][0], v["bbox"][3]]
    errors, _ = rules.validate(doc)
    assert any("bbox" in e for e in errors)


def test_key_order(doc):
    v = value(doc, "⌀25 ±0.15")
    v["raw"] = v.pop("raw")
    errors, _ = rules.validate(doc)
    assert any("keys out of schema order" in e for e in errors)


def test_unused_feature_is_a_warning_not_an_error(doc):
    doc["features"].append(
        {
            "id": "slot_left",
            "type": "slot",
            "label": "left slot",
            "description": "Slot with no callout.",
            "page": 1,
        }
    )
    assert rules.validate(doc) == ([], ["feature slot_left is not used by any value"])


# limits arithmetic


@pytest.mark.parametrize(
    "style, value_, limits, message",
    [
        ("plus_minus", 25, {"lower": 25.1, "upper": 25.2}, "nominal 25 lies outside its limits"),
        (
            "limits",
            [34.8, 35.2],
            {"lower": 34.8, "upper": 35.0},
            "limit dimension value must equal",
        ),
        ("geometric_zone", 0.2, {"lower": 0.1, "upper": 0.2}, "geometric zone limits must be"),
        ("geometric_zone", 0.2, {"lower": 0, "upper": 0.3}, "geometric zone limits must be"),
        ("unilateral", 35, {"lower": 35.2, "upper": 35.0}, "limits lower 35.2 above upper 35.0"),
    ],
)
def test_check_limits_rejects(style, value_, limits, message):
    errors = rules.check_limits({"tolerance_style": style, "value": value_, "limits": limits})
    assert len(errors) == 1 and errors[0].startswith(message)


@pytest.mark.parametrize(
    "style, value_, limits",
    [
        ("plus_minus", 25, {"lower": 24.85, "upper": 25.15}),
        ("unilateral", 35, {"lower": 34.8, "upper": 35}),
        ("bilateral_unequal", 20, {"lower": 19.9, "upper": 20.05}),
        ("limits", [34.8, 35.2], {"lower": 34.8, "upper": 35.2}),
        ("geometric_zone", 0.75, {"lower": 0, "upper": 0.75}),
        ("basic", 75, None),
    ],
)
def test_check_limits_accepts(style, value_, limits):
    assert rules.check_limits({"tolerance_style": style, "value": value_, "limits": limits}) == []


# page coverage


def covering(doc, page_count, pages):
    """The document with page_count and page_coverage set, keys in schema order."""
    rest = {k: v for k, v in doc.items() if k not in ("drawing", "page_count")}
    return {"drawing": doc["drawing"], "page_count": page_count, "page_coverage": pages, **rest}


def test_page_coverage_is_optional_and_follows_page_count(doc):
    assert rules.validate(covering(doc, 1, [1])) == ([], [])


def test_page_coverage_key_order(doc):
    doc["page_coverage"] = [1]
    errors, _ = rules.validate(doc)
    assert any("document keys must be" in e for e in errors)


def test_value_outside_page_coverage(doc):
    errors, _ = rules.validate(covering(doc, 2, [2]))
    assert f"value {doc['values'][0]['id']}: page 1 is outside page_coverage [2]" in errors


def test_page_coverage_within_page_count_and_ascending(doc):
    errors, _ = rules.validate(covering(doc, 2, [2, 1, 3]))
    assert "page_coverage page 3 beyond page_count" in errors
    assert "page_coverage must list pages in ascending order" in errors
