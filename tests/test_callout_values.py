import pytest

from resourcly.callout_values import (
    datum_letter,
    feature_type,
    needs_symbol,
    readings,
    sheet_units,
    value_fields,
)


def _one(transcription, framed=False, letters=10):
    found = readings(transcription, framed=framed, letters=letters)
    assert len(found) == 1, found
    return found[0]


def test_a_frame_is_spelled_the_gold_way() -> None:
    frame = {
        "symbol_name": "position",
        "tolerance": "Ø.05",
        "modifiers": ["M"],
        "datums": ["A", "B(M)", "C (M)"],
    }
    reading = _one({"lines": [], "feature_control_frames": [frame]}, framed=True)

    assert reading["raw"] == "⌖ ⌀.05Ⓜ | A | BⓂ | CⓂ"
    assert (reading["callout"], reading["kind"]) == ("feature_control_frame", "position")
    assert reading["tolerance_style"] == "geometric_zone"
    assert reading["datums"] == ["A", "BⓂ", "CⓂ"]


@pytest.mark.parametrize(
    ("symbol_name", "kind"),
    [
        ("profile of a surface", "profile_of_a_surface"),
        ("⌓", "profile_of_a_surface"),
        ("flatness (parallelogram)", "flatness"),
        ("perpendicularity", "perpendicularity"),
        ("true position", "position"),
        ("⊥", "perpendicularity"),
    ],
)
def test_the_characteristic_comes_from_the_symbol_name(symbol_name, kind) -> None:
    frame = {"symbol_name": symbol_name, "tolerance": "0.2", "datums": []}
    assert _one({"lines": [], "feature_control_frames": [frame]})["kind"] == kind


def test_a_frame_with_no_named_characteristic_is_dropped() -> None:
    frame = {"symbol_name": "", "tolerance": "0.2", "datums": ["A"]}
    assert readings({"lines": [], "feature_control_frames": [frame]}) == []


@pytest.mark.parametrize(
    ("lines", "raw", "kind", "style"),
    [
        (["Ø20 +0.05", "-0.10"], "⌀20 +0.05/-0.10", "diameter", "bilateral_unequal"),
        (["Ø35", "0", "-0.2"], "⌀35 0/-0.2", "diameter", "unilateral"),
        (["Ø35.2", "Ø34.8"], "⌀35.2/34.8", "diameter", "limits"),
        (["Ø34.8 - 35.2"], "⌀34.8 - 35.2", "diameter", "limits"),
        (["Ø34.8", "- Ø35.2"], "⌀34.8 - 35.2", "diameter", "limits"),
        (["- Ø35.2", "Ø34.8"], "⌀34.8 - 35.2", "diameter", "limits"),
        (["2X Ø.438 ±.005"], "2X ⌀.438 ±.005", "diameter", "plus_minus"),
        (["24X R.125 ±.020"], "24X R.125 ±.020", "radius", "plus_minus"),
        (["60° ±0.5°"], "60° ±0.5°", "angular", "plus_minus"),
        (["(1.106)"], "(1.106)", "linear", "reference"),
        (["(SR.500)"], "(SR.500)", "radius", "reference"),
        (["4X .82 ±.06"], "4X .82 ±.06", "linear", "plus_minus"),
        (["2X ⌲ 1.00 : 3.00"], "2X ⌲ 1.00 : 3.00", "angular", "none"),
    ],
)
def test_dimension_lines_are_joined_and_classified(lines, raw, kind, style) -> None:
    reading = _one({"lines": lines, "feature_control_frames": []})

    assert (reading["raw"], reading["callout"]) == (raw, "dimension")
    assert (reading["kind"], reading["tolerance_style"]) == (kind, style)


def test_lines_that_repeat_a_frame_are_not_read_twice() -> None:
    frame = {"symbol_name": "position", "tolerance": "0.75", "datums": ["A", "B", "C"]}
    found = readings({"lines": ["0.75 A B C"], "feature_control_frames": [frame]})

    assert [r["callout"] for r in found] == ["feature_control_frame"]


@pytest.mark.parametrize(
    "line", ["4X INDIVIDUALLY", "2 SURFACES", "SWITCH MOUNTING LOCATIONS", "2 COPLANAR SURFACES"]
)
def test_words_are_a_note(line) -> None:
    reading = _one({"lines": [line], "feature_control_frames": []})

    assert (reading["callout"], reading["kind"], reading["raw"]) == ("note", "note", line)


def test_a_letter_in_a_small_frame_is_a_datum_feature_symbol() -> None:
    reading = _one({"lines": ["B"], "feature_control_frames": []}, framed=True, letters=2)

    assert (reading["callout"], reading["kind"], reading["raw"]) == (
        "datum_feature_symbol",
        "datum_feature",
        "B",
    )


def test_a_letter_and_number_outside_a_frame_is_a_datum_target() -> None:
    reading = _one({"lines": ["J1"], "feature_control_frames": []})

    assert (reading["callout"], reading["kind"], reading["raw"]) == (
        "datum_target",
        "datum_target",
        "J1",
    )


def test_a_lone_letter_outside_a_frame_is_dropped() -> None:
    assert readings({"lines": ["X"], "feature_control_frames": []}) == []


def test_a_malformed_transcription_reads_as_nothing() -> None:
    assert readings(None) == []
    assert readings({"lines": "Ø20", "feature_control_frames": [None, "x"]}) == []


def _numbers(fields: dict) -> dict:
    return {key: fields[key] for key in ("value", "limits", "unit")}


def test_value_fields_come_from_the_printed_numbers() -> None:
    plus_minus = _one({"lines": ["Ø25 ±0.15"], "feature_control_frames": []})
    angle = _one({"lines": ["60° ±0.5°"], "feature_control_frames": []})
    frame = _one(
        {"lines": [], "feature_control_frames": [{"symbol_name": "flatness", "tolerance": ".01"}]}
    )
    datum = _one({"lines": ["A"], "feature_control_frames": []}, framed=True, letters=1)

    assert _numbers(value_fields(plus_minus, "mm")) == {
        "value": 25,
        "limits": {"lower": 24.85, "upper": 25.15},
        "unit": "mm",
    }
    assert value_fields(angle, "mm")["unit"] == "deg"
    assert _numbers(value_fields(frame, "in")) == {
        "value": 0.01,
        "limits": {"lower": 0, "upper": 0.01},
        "unit": "in",
    }
    assert _numbers(value_fields(datum, "in")) == {"value": None, "limits": None, "unit": None}


def test_value_fields_keep_the_reading_as_it_is_when_the_numbers_parse() -> None:
    reading = _one({"lines": ["2X Ø.438 ±.005"], "feature_control_frames": []})

    fields = value_fields(reading, "in")

    assert {k: fields[k] for k in ("callout", "kind", "tolerance_style", "datums")} == {
        "callout": "dimension",
        "kind": "diameter",
        "tolerance_style": "plus_minus",
        "datums": [],
    }


def test_limits_out_of_order_are_a_misread_and_keep_no_number() -> None:
    reading = _one({"lines": ["Ø35.2 - 34.8"], "feature_control_frames": []})
    before = dict(reading)

    fields = value_fields(reading, "mm")

    assert (fields["value"], fields["limits"], fields["tolerance_style"]) == (None, None, "none")
    assert reading == before  # the argument is not changed


def test_a_frame_whose_zone_does_not_parse_becomes_a_note() -> None:
    frame = {"symbol_name": "position", "tolerance": "±.020", "datums": ["A"]}
    reading = _one({"lines": [], "feature_control_frames": [frame]})
    before = dict(reading)

    fields = value_fields(reading, "in")

    assert {k: fields[k] for k in ("callout", "kind", "tolerance_style", "datums", "value")} == {
        "callout": "note",
        "kind": "note",
        "tolerance_style": "none",
        "datums": [],
        "value": None,
    }
    assert reading == before


@pytest.mark.parametrize(
    ("notes", "raws", "units"),
    [
        (["5. UNITS: INCHES"], [], ("in", "stated")),
        (["UNITS: MILLIMETERS"], [], ("mm", "stated")),
        ([], ["⌀.438 ±.005", "⌖ ⌀.05Ⓜ | A"], ("in", "inferred")),
        ([], ["⌀25 ±0.15", "▱ 0.2"], ("mm", "inferred")),
        ([], [], (None, None)),
    ],
)
def test_sheet_units_are_stated_or_inferred(notes, raws, units) -> None:
    assert sheet_units(notes, raws) == units


@pytest.mark.parametrize(
    ("raws", "expected"),
    [
        (["4X ⌀.281 ±.008", "⌖ ⌀.015 | E | A | B"], "pattern"),
        (["⌀.438 ±.005", "⌖ ⌀.02 | A | B"], "hole"),
        (["24X R.125 ±.020"], "pattern"),
        (["R.50 ±.02"], "fillet"),
        (["▱ .01"], "plane"),
        (["A"], "plane"),
        (["⌖ .025 | D | C | J"], "hole"),
    ],
)
def test_feature_type_follows_a_rule_on_what_the_callout_says(raws, expected) -> None:
    group = [
        _one({"lines": [raw], "feature_control_frames": []}, framed=True, letters=1)
        if raw == "A"
        else _reading_for(raw)
        for raw in raws
    ]
    assert feature_type(group) == expected


def _reading_for(raw: str) -> dict:
    if " | " in raw or raw[0] in "▱⌖":
        symbol, zone = raw.split(" | ")[0].split()
        names = {"⌖": "position", "▱": "flatness"}
        frame = {"symbol_name": names[symbol], "tolerance": zone, "datums": raw.split(" | ")[1:]}
        return _one({"lines": [], "feature_control_frames": [frame]})
    return _one({"lines": [raw], "feature_control_frames": []})


def test_a_frame_whose_symbol_was_not_named_needs_a_symbol() -> None:
    unnamed = {"symbol_name": "", "tolerance": "1.5", "datums": ["A"]}
    named = {"symbol_name": "flatness", "tolerance": "0.2"}

    assert needs_symbol({"lines": [], "feature_control_frames": [unnamed, named]})
    assert not needs_symbol({"lines": [], "feature_control_frames": [named]})
    assert not needs_symbol(None)


@pytest.mark.parametrize(
    ("answer", "letter"),
    [({"letter": "B"}, "B"), ({"letter": " c "}, None), ({"letter": "AB"}, None), (None, None)],
)
def test_a_datum_letter_is_one_capital_letter(answer, letter) -> None:
    assert datum_letter(answer) == letter
