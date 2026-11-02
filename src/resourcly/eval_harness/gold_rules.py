"""The drawing gold checks the package models do not make.

The package models validate a gold document first, in `evals check`, and
evals/gold/schema.json is generated from them. These rules run once the models accept it: what
gold needs beyond what a reading needs, such as limits that agree with the printed value, and what
a schema cannot express, such as key order, unique ids and feature_id references. Features that no
value uses are warnings, since a gold file may list a feature for context.
"""

import json
from typing import Any

from resourcly.bootstrap import PROJECT_ROOT

SCHEMA = json.loads((PROJECT_ROOT / "evals" / "gold" / "schema.json").read_text(encoding="utf-8"))

DOC_KEYS = list(SCHEMA["properties"])
OPTIONAL_DOC_KEYS = ("page_coverage",)
TITLE_KEYS = list(SCHEMA["$defs"]["TitleBlock"]["properties"])
FEATURE_KEYS = list(SCHEMA["$defs"]["Feature"]["properties"])
VALUE_KEYS = list(SCHEMA["$defs"]["Value"]["properties"])
TOLERANCED = ("limits", "plus_minus", "unilateral", "bilateral_unequal", "geometric_zone")
FLOAT_TOLERANCE = 1e-9  # limits are decimal arithmetic stored as floats
LOW_CONFIDENCE = 0.7  # records below this are listed in evals/gold/README.md for the reviewer


def validate(doc: Any) -> tuple[list[str], list[str]]:
    """Return (errors, warnings) for one gold document that the package models accept."""
    expected = [key for key in DOC_KEYS if key not in OPTIONAL_DOC_KEYS or key in doc]
    if list(doc) != expected:
        return [f"document keys must be {', '.join(expected)} in this order: {list(doc)}"], []
    return check_rules(doc)


def tally(doc: Any) -> str:
    """The size of a valid document, and how many values a reviewer should look at first."""
    low = sum(1 for v in doc["values"] if v["confidence"] < LOW_CONFIDENCE)
    return (
        f"{doc['page_count']} page(s), {len(doc['features'])} features, "
        f"{len(doc['values'])} values, {low} below confidence {LOW_CONFIDENCE}"
    )


def duplicates(ids):
    return sorted({i for i in ids if ids.count(i) > 1})


def check_rules(doc):
    """Return (errors, warnings) for the rules beyond the models. Assumes the document keys and the
    models passed."""
    errors, warnings = [], []
    coverage = doc.get("page_coverage")
    if coverage is not None:
        errors += [
            f"page_coverage page {page} beyond page_count"
            for page in coverage
            if page > doc["page_count"]
        ]
        if coverage != sorted(coverage):
            errors.append("page_coverage must list pages in ascending order")
    if list(doc["title_block"]) != TITLE_KEYS:
        errors.append("title_block keys out of schema order")

    feature_ids = [f["id"] for f in doc["features"]]
    value_ids = [v["id"] for v in doc["values"]]
    errors += [f"duplicate feature id {i}" for i in duplicates(feature_ids)]
    errors += [f"duplicate value id {i}" for i in duplicates(value_ids)]
    prefixes = {i.split("-")[0] for i in value_ids}
    if len(prefixes) > 1:
        errors.append(f"value ids use more than one drawing prefix: {sorted(prefixes)}")

    for record, keys in [(f, FEATURE_KEYS) for f in doc["features"]] + [
        (v, VALUE_KEYS) for v in doc["values"]
    ]:
        label = f"{'value' if keys is VALUE_KEYS else 'feature'} {record['id']}"
        if list(record) != keys:
            errors.append(f"{label}: keys out of schema order")
        text = "meaning" if keys is VALUE_KEYS else "description"
        if not record[text]:
            errors.append(f"{label}: {text} must not be empty")
        if record["page"] > doc["page_count"]:
            errors.append(f"{label}: page {record['page']} beyond page_count")
        if keys is VALUE_KEYS and coverage is not None and record["page"] not in coverage:
            errors.append(f"{label}: page {record['page']} is outside page_coverage {coverage}")

    used = set()
    for v in doc["values"]:
        label = f"value {v['id']}"
        feature_id = v["feature_id"]
        if feature_id is None:
            if v["callout"] != "title_block":
                errors.append(f"{label}: feature_id is null but callout is {v['callout']}")
        elif feature_id not in feature_ids:
            errors.append(f"{label}: feature_id {feature_id} does not resolve")
        else:
            used.add(feature_id)
        x0, y0, x1, y1 = v["bbox"]
        if not (x0 < x1 and y0 < y1):
            errors.append(f"{label}: bbox is not [x0, y0, x1, y1] with x0 < x1 and y0 < y1")
        style = check_style(v)
        errors += [f"{label}: {e}" for e in style or check_limits(v)]

    warnings += [f"feature {i} is not used by any value" for i in sorted(set(feature_ids) - used)]
    return errors, warnings


def check_style(v):
    """Check that the tolerance style fits the callout, the value and the limits.

    A frame is a geometric zone. A toleranced value carries limits and, except a limit dimension,
    whose pair the models check, one number; a basic, reference or text value has no limits.
    """
    style, value, limits = v["tolerance_style"], v["value"], v["limits"]
    errors = []
    if v["callout"] == "feature_control_frame" and style != "geometric_zone":
        errors.append("a feature_control_frame has tolerance_style geometric_zone")
    if style in TOLERANCED and limits is None:
        errors.append(f"a {style} value needs limits")
    if style not in TOLERANCED and limits is not None:
        errors.append(f"a {style} value takes no limits")
    if style in TOLERANCED and style != "limits" and not isinstance(value, int | float):
        errors.append(f"a {style} value must be a number")
    return errors


def check_limits(v):
    """Check that limits agree with the printed value, once check_style passed."""
    style, value, limits = v["tolerance_style"], v["value"], v["limits"]
    if limits is None:
        return []
    lower, upper = limits["lower"], limits["upper"]
    if lower > upper + FLOAT_TOLERANCE:
        return [f"limits lower {lower} above upper {upper}"]
    if style == "limits":
        if abs(value[0] - lower) > FLOAT_TOLERANCE or abs(value[1] - upper) > FLOAT_TOLERANCE:
            return ["limit dimension value must equal [limits.lower, limits.upper]"]
    elif style == "geometric_zone":
        if abs(lower) > FLOAT_TOLERANCE or abs(upper - value) > FLOAT_TOLERANCE:
            return ["geometric zone limits must be {lower: 0, upper: value}"]
    elif not lower - FLOAT_TOLERANCE <= value <= upper + FLOAT_TOLERANCE:
        return [f"nominal {value} lies outside its limits"]
    return []
