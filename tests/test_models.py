import copy

from resourcly.models import undefined_datums, validate_document


def test_sample_document_is_valid(ctc01: dict) -> None:
    document, issues = validate_document(ctc01)

    assert issues == []
    assert len(document.values) == 17
    assert document.values[0].value == (34.8, 35.2)


def test_bad_record_reports_each_field(ctc01: dict) -> None:
    bad = copy.deepcopy(ctc01)
    bad["values"][1] |= {"kind": "diameter", "bbox": [0.5, 0.5, 0.4, 0.6], "confidence": 1.5}
    bad["values"][2]["callout"] = "arrow"

    _, issues = validate_document(bad)

    found = {tuple(issue.loc): issue.message for issue in issues}
    assert set(found) == {("values", 1, "confidence"), ("values", 2, "callout")}
    assert found[("values", 1, "confidence")] == "must be at most 1"


def test_gold_needs_a_confidence_but_a_reading_may_leave_it_out(ctc01: dict) -> None:
    reading = copy.deepcopy(ctc01)
    reading["values"][3]["confidence"] = None

    _, issues = validate_document(reading)
    document, reader_issues = validate_document(reading, gold=False)

    assert [(tuple(i.loc), i.message) for i in issues] == [
        (("values", 3, "confidence"), "gold needs a confidence from 0 to 1")
    ]
    assert reader_issues == []
    assert document.values[3].confidence is None


def test_record_rules_point_at_the_field(ctc01: dict) -> None:
    bad = copy.deepcopy(ctc01)
    bad["values"][1] |= {"kind": "diameter", "bbox": [0.5, 0.5, 0.4, 0.6]}

    _, issues = validate_document(bad)

    found = {tuple(issue.loc): issue.message for issue in issues}
    assert set(found) == {("values", 1, "kind"), ("values", 1, "bbox")}
    assert "flatness" in found[("values", 1, "kind")]


def test_document_rules_point_at_the_record(ctc01: dict) -> None:
    bad = copy.deepcopy(ctc01)
    bad["values"][3]["feature_id"] = "no_such_feature"
    bad["values"][4]["id"] = bad["values"][0]["id"]
    bad["features"][0]["page"] = 2

    _, issues = validate_document(bad)

    assert {tuple(issue.loc) for issue in issues} == {
        ("values", 3, "feature_id"),
        ("values", 4, "id"),
        ("features", 0, "page"),
    }


def test_unknown_fields_are_rejected(ctc01: dict) -> None:
    bad = copy.deepcopy(ctc01)
    bad["values"][0]["colour"] = "red"

    _, issues = validate_document(bad)

    assert [issue.loc for issue in issues] == [["values", 0, "colour"]]


def _issues_for(document: dict) -> dict[tuple, str]:
    _, issues = validate_document(document)
    return {tuple(issue.loc): issue.message for issue in issues}


def test_geometric_zone_starts_at_zero(ctc01: dict) -> None:
    ctc01["values"][1]["limits"] = {"lower": 0.1, "upper": 0.2}

    assert _issues_for(ctc01) == {("values", 1, "limits"): "lower must be 0 for a geometric zone"}


def test_limits_style_needs_a_range(ctc01: dict) -> None:
    ctc01["values"][0]["value"] = 35

    assert _issues_for(ctc01) == {("values", 0, "value"): "a limit dimension stores [lower, upper]"}


def test_value_ids_carry_the_drawing_prefix(ctc01: dict) -> None:
    ctc01["values"][3]["id"] = "zzz-03"

    assert _issues_for(ctc01) == {("values", 3, "id"): "must start with 'ctc01-' for this drawing"}


def test_unit_fits_the_kind(ctc01: dict) -> None:
    ctc01["values"][12]["unit"] = "mm"
    ctc01["values"][6]["unit"] = "deg"

    assert _issues_for(ctc01) == {
        ("values", 12, "unit"): "an angle is measured in deg",
        ("values", 6, "unit"): "deg is only for angular dimensions",
    }


def test_bad_value_names_the_allowed_shapes(ctc01: dict) -> None:
    ctc01["values"][1]["value"] = "0.2"

    assert _issues_for(ctc01) == {
        ("values", 1, "value"): "must be a number, [lower, upper] or null"
    }


def test_datums_must_be_defined(ctc01: dict) -> None:
    ctc01["values"][4]["datums"] = ["A", "BⓂ", "Z"]
    document, _ = validate_document(ctc01)

    assert [(i.loc, i.message) for i in undefined_datums(document)] == [
        (["values", 4, "datums"], "no datum feature symbol defines Z")
    ]


def test_datum_targets_define_their_datum(ctc01: dict) -> None:
    target = copy.deepcopy(ctc01["values"][2])
    target |= {"id": "ctc01-18", "raw": "⌀6 Z1", "callout": "datum_target", "kind": "datum_target"}
    ctc01["values"].append(target)
    ctc01["values"][4]["datums"] = ["A", "Z(M)"]
    document, _ = validate_document(ctc01)

    assert undefined_datums(document) == []


def test_page_coverage_limits_the_pages_values_may_sit_on(ctc01: dict) -> None:
    ctc01 |= {"page_count": 2, "page_coverage": [2, 3]}
    ctc01["values"][5]["page"] = 2

    found = _issues_for(ctc01)

    assert found[("page_coverage",)] == "page 3 is beyond page_count 2"
    assert found[("values", 0, "page")] == "page 1 is outside page_coverage [2, 3]"
    assert ("values", 5, "page") not in found


def test_page_coverage_is_dumped_only_when_set(ctc01: dict) -> None:
    document, _ = validate_document(ctc01)
    assert "page_coverage" not in document.model_dump(mode="json")

    ctc01 = {"drawing": ctc01.pop("drawing"), "page_count": 1, "page_coverage": [1], **ctc01}
    document, _ = validate_document(ctc01)
    assert list(document.model_dump(mode="json"))[:3] == ["drawing", "page_count", "page_coverage"]
