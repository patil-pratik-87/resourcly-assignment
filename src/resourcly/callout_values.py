"""Turn what a model transcribed from a callout into value records, with plain code.

A model is asked only to copy what it sees, in this shape:

    {"lines": ["Ø20 +0.05", "-0.10"],
     "feature_control_frames": [{"symbol_name": "position", "tolerance": "0.75",
                                 "modifiers": [], "datums": ["A", "B", "C"]}]}

Everything else is decided here: which lines are a frame's cells read again, which lines form one
stacked dimension, how `raw` is spelled, the callout and kind, the tolerance style, and the value,
limits and unit, which come from the printed numbers by the same arithmetic the gold check uses.
"""

import re
from decimal import Decimal
from typing import Any

NUM = r"(\d*\.?\d+)"
SIGNED = r"([+-]?\d*\.?\d+)"
PLUS_MINUS = re.compile(NUM + r"°?\s*±\s*" + NUM)
SIGNED_PAIR = re.compile(NUM + r"°?\s+" + SIGNED + r"/" + SIGNED + r"(?:\s|$)")
RANGE = re.compile(NUM + r"\s+-\s+" + NUM)
STACKED = re.compile(NUM + r"/" + NUM + r"$")
ZONE = re.compile(r"^S?⌀?" + NUM)
QUANTITY = re.compile(r"^\d+X\s+")
FIRST_NUMBER = re.compile(r"(?<![\d.])" + NUM)
TOLERANCED = {"limits", "plus_minus", "unilateral", "bilateral_unequal", "geometric_zone"}

SYMBOLS = {  # checked in order; the first key found in the symbol name wins
    "surface": ("⌓", "profile_of_a_surface"),
    "⌓": ("⌓", "profile_of_a_surface"),
    "profile": ("⌓", "profile_of_a_surface"),
    "line": ("⌒", "profile_of_a_line"),
    "⌒": ("⌒", "profile_of_a_line"),
    "flat": ("▱", "flatness"),
    "▱": ("▱", "flatness"),
    "perpendic": ("⊥", "perpendicularity"),
    "⊥": ("⊥", "perpendicularity"),
    "parallel": ("∥", "parallelism"),
    "∥": ("∥", "parallelism"),
    "angular": ("∠", "angularity"),
    "∠": ("∠", "angularity"),
    "cylindric": ("⌭", "cylindricity"),
    "circular": ("○", "circularity"),
    "round": ("○", "circularity"),
    "total": ("⌰", "total_runout"),
    "runout": ("↗", "circular_runout"),
    "↗": ("↗", "circular_runout"),
    "concentric": ("◎", "concentricity"),
    "symmetr": ("⌯", "symmetry"),
    "straight": ("⏤", "straightness"),
    "position": ("⌖", "position"),
    "⌖": ("⌖", "position"),
    "true": ("⌖", "position"),
}
MODIFIERS = {"M": "Ⓜ", "L": "Ⓛ", "P": "Ⓟ", "U": "Ⓤ"}
SIGNED_LINE = re.compile(r"^[+-]\d*\.?\d+$|^0$")
NUMBER = re.compile(r"\d*\.?\d+")
NUMBER_ONLY = re.compile(r"⌀?\d*\.?\d+")
RANGE_END = re.compile(r"-\s+⌀?(\d*\.?\d+)")
WORDS_THAT_ARE_NOT_NOTES = {"MAX", "MIN", "THRU", "TYP", "REF", "DEEP", "EQ", "SP", "ST"}


def readings(transcription: Any, framed: bool = False, letters: int = 0) -> list[dict[str, Any]]:
    """The readings in one callout: raw, callout, kind, tolerance_style and datums each.

    `framed` and `letters` describe the callout box, so a single letter in a small frame is known
    to be a datum feature symbol.
    """
    data = transcription if isinstance(transcription, dict) else {}
    frames = [f for f in _list(data.get("feature_control_frames")) if isinstance(f, dict)]
    lines = [str(x).strip() for x in _list(data.get("lines")) if str(x).strip()]
    found = [r for r in map(_frame, frames) if r]
    for raw in _dimension_raws(lines, frames):
        reading = _line_reading(raw, framed and letters <= 3)
        if reading:
            found.append(reading)
    return found


def needs_symbol(transcription: Any) -> bool:
    """Whether a frame in the transcription has a tolerance but no characteristic named."""
    data = transcription if isinstance(transcription, dict) else {}
    frames = [f for f in _list(data.get("feature_control_frames")) if isinstance(f, dict)]
    return any(
        _characteristic(f) is None and NUMBER.search(str(f.get("tolerance") or "")) for f in frames
    )


def name_symbols(transcription: dict[str, Any], symbol_name: str) -> dict[str, Any]:
    """The transcription with `symbol_name` given to each frame that named no characteristic."""
    frames = [
        {**f, "symbol_name": symbol_name}
        if isinstance(f, dict) and _characteristic(f) is None
        else f
        for f in _list(transcription.get("feature_control_frames"))
    ]
    return {**transcription, "feature_control_frames": frames}


def datum_letter(answer: Any) -> str | None:
    """The letter of a datum feature symbol from {"letter": "B"}, or None."""
    letter = answer.get("letter") if isinstance(answer, dict) else None
    return letter if isinstance(letter, str) and re.fullmatch(r"[A-Z]", letter) else None


def value_fields(reading: dict[str, Any], units: str | None) -> dict[str, Any]:
    """The reading's value, limits and unit, with its callout, kind, style and datums settled.

    value and limits come from the raw text, and the unit from the sheet's units. A toleranced
    reading whose numbers cannot be parsed, or whose limits are out of order (a misread digit),
    keeps no number and its tolerance style becomes none; such a frame becomes a note. The
    reading itself is not changed.
    """
    kept = {key: reading[key] for key in ("callout", "kind", "tolerance_style", "datums")}
    nothing = {"value": None, "limits": None, "unit": None}
    if reading["callout"] not in ("dimension", "feature_control_frame"):
        return {**kept, **nothing}
    derived = derive(reading)
    if derived is None or (derived[1] is not None and derived[1][0] > derived[1][1]):
        if reading["tolerance_style"] in TOLERANCED:
            kept["tolerance_style"] = "none"
            if reading["callout"] == "feature_control_frame":
                kept.update(callout="note", kind="note", datums=[])
        return {**kept, **nothing}
    value, limits = derived
    unit = "deg" if reading["kind"] == "angular" else units
    return {
        **kept,
        "value": [_number(v) for v in value] if isinstance(value, list) else _number(value),
        "limits": None
        if limits is None
        else {"lower": _number(limits[0]), "upper": _number(limits[1])},
        "unit": unit if value is not None else None,
    }


def derive(record: dict[str, Any]) -> tuple[Any, Any] | None:
    """(value, limits) derived from raw, with Decimals, or None when raw cannot be parsed."""
    raw, style = record["raw"], record["tolerance_style"]
    if record["callout"] == "feature_control_frame":
        first_cell = raw.split(" | ")[0].split()
        match = ZONE.match(first_cell[1]) if len(first_cell) > 1 else None
        if not match:
            return None
        zone = Decimal(match.group(1))
        return zone, (Decimal(0), zone)
    if style == "none":
        return None  # an untoleranced ratio or note: nothing to derive
    if style not in TOLERANCED:
        match = FIRST_NUMBER.search(QUANTITY.sub("", raw))
        return (Decimal(match.group(1)) if match else None), None
    if match := PLUS_MINUS.search(raw):
        nominal, tolerance = map(Decimal, match.groups())
        return nominal, (nominal - tolerance, nominal + tolerance)
    if match := SIGNED_PAIR.search(raw):
        nominal, first, second = map(Decimal, match.groups())
        return nominal, (nominal + min(first, second), nominal + max(first, second))
    if match := RANGE.search(raw):
        lower, upper = map(Decimal, match.groups())
        return [lower, upper], (lower, upper)
    if match := STACKED.search(raw):
        upper, lower = map(Decimal, match.groups())
        return [lower, upper], (lower, upper)
    return None


def sheet_units(notes: list[str], raws: list[str]) -> tuple[str | None, str | None]:
    """(units, units_source): stated in a note, else inferred from how the numbers are written.

    Metric drawings under ASME Y14.5 write a leading zero (0.2); inch drawings do not (.438).
    """
    text = " ".join(notes).upper()
    if "INCH" in text:
        return "in", "stated"
    if "MILLIMET" in text:
        return "mm", "stated"
    joined = " ".join(raws)
    metric = len(re.findall(r"(?<![\d.])0\.\d", joined))
    inch = len(re.findall(r"(?<![\d.])\.\d", joined))
    if metric == inch == 0:
        return None, None
    return ("mm" if metric >= inch else "in"), "inferred"


def feature_type(group: list[dict[str, Any]]) -> str:
    """A feature type for the readings of one callout, by a fixed rule on what they say.

    A count such as "4X" makes a pattern, a diameter or a position a hole, a radius a fillet, and
    a datum, a form or an orientation tolerance a plane.
    """
    raws = [r["raw"] for r in group]
    kinds = {r["kind"] for r in group}
    if any(QUANTITY.match(raw) for raw in raws):
        return "pattern"
    if "diameter" in kinds or "position" in kinds:
        return "hole"
    if "radius" in kinds:
        return "fillet"
    if kinds & {"datum_target", "linear"}:
        return "slot"
    if kinds - {"note"}:
        return "plane"
    return "other"


def _characteristic(frame: dict[str, Any]) -> tuple[str, str] | None:
    """(symbol, kind) named by the frame's symbol_name, or None."""
    name = str(frame.get("symbol_name") or "").lower()
    return next((found for key, found in SYMBOLS.items() if key in name), None)


def _frame(frame: dict[str, Any]) -> dict[str, Any] | None:
    match = _characteristic(frame)
    tolerance = _diameter(str(frame.get("tolerance") or "")).replace(" ", "")
    tolerance = re.sub(r"\(?([MLPU])\)?$", lambda m: MODIFIERS[m.group(1)], tolerance)
    if match is None or not NUMBER.search(tolerance):
        return None
    symbol, kind = match
    for modifier in _list(frame.get("modifiers")):
        mark = MODIFIERS.get(str(modifier).strip("() ").upper()[:1], "")
        if mark and mark not in tolerance:
            tolerance += mark
    datums = []
    for datum in _list(frame.get("datums")):
        text = str(datum).strip()
        if re.match(r"[A-Z]", text):
            marks = "".join(MODIFIERS[m] for m in re.findall(r"\(?\s*([MLPU])\s*\)?", text[1:]))
            datums.append(text[0] + marks)
    return {
        "raw": " | ".join([f"{symbol} {tolerance}", *datums]),
        "callout": "feature_control_frame",
        "kind": kind,
        "tolerance_style": "geometric_zone",
        "datums": datums,
    }


def _dimension_raws(lines: list[str], frames: list[dict[str, Any]]) -> list[str]:
    """Join the lines that are not frame cells into dimensions, spelled the gold way.

    "Ø20 +0.05" + "-0.10"   -> "⌀20 +0.05/-0.10"   (unequal tolerance stacked on two lines)
    "Ø35" + "0" + "-0.2"    -> "⌀35 0/-0.2"
    "Ø35.2" + "Ø34.8"       -> "⌀35.2/34.8"        (limits stacked, upper over lower)
    "Ø34.8" + "- Ø35.2"     -> "⌀34.8 - 35.2"      (a limit range split at its dash)
    "- Ø35.2" + "Ø34.8"     -> "⌀34.8 - 35.2"      (stacked limits, a leader tick read as a dash)
    """
    cells = _frame_cells(frames)
    kept = []
    for line in map(_diameter, lines):
        words = line.split()
        if cells and words and all(_cell(word) in cells for word in words):
            continue
        kept.append(line)
    joined: list[str] = []
    for line in kept:
        previous = joined[-1] if joined else ""
        if previous and SIGNED_LINE.match(line):
            if re.search(r"\s[+-]?\d*\.?\d+$", previous) and "/" not in previous:
                joined[-1] = f"{previous}/{line}"
                continue
            if re.search(r"\d$", previous):
                joined[-1] = f"{previous} {line}"
                continue
        if previous and NUMBER_ONLY.fullmatch(previous) and NUMBER_ONLY.fullmatch(line):
            joined[-1] = f"{previous}/{line.lstrip('⌀')}"
            continue
        upper = RANGE_END.fullmatch(line)
        if previous and NUMBER_ONLY.fullmatch(previous) and upper:
            joined[-1] = f"{previous} - {upper.group(1)}"
            continue
        if NUMBER_ONLY.fullmatch(line) and (above := RANGE_END.fullmatch(previous)):
            joined[-1] = f"{line} - {above.group(1)}"
            continue
        joined.append(line)
    return [re.sub(r"(\d)\s+([+-]?\d*\.?\d+)\s+([+-]\d*\.?\d+)$", r"\1 \2/\3", r) for r in joined]


def _line_reading(raw: str, in_small_frame: bool) -> dict[str, Any] | None:
    plain = {"tolerance_style": "none", "datums": []}
    if re.fullmatch(r"[A-Z]", raw):
        if in_small_frame:
            return {"raw": raw, "callout": "datum_feature_symbol", "kind": "datum_feature", **plain}
        return None  # an axis or point label
    if re.fullmatch(r"[A-Z]\d+", raw):
        return {"raw": raw, "callout": "datum_target", "kind": "datum_target", **plain}
    if _is_note(raw):
        return {"raw": raw, "callout": "note", "kind": "note", **plain}
    if not NUMBER.search(raw):
        return None
    body = QUANTITY.sub("", raw)
    if "°" in raw or ":" in raw:
        kind = "angular"
    elif "⌀" in body:
        kind = "diameter"
    elif re.match(r"\(?[SC]?R", body):
        kind = "radius"
    else:
        kind = "linear"
    return {
        "raw": raw,
        "callout": "dimension",
        "kind": kind,
        **plain,
        "tolerance_style": _style(raw),
    }


def _style(raw: str) -> str:
    if ":" in raw:
        return "none"
    if "±" in raw:
        return "plus_minus"
    pair = re.search(r"\d\s+([+-]?\d*\.?\d+)/([+-]?\d*\.?\d+)$", raw)
    if pair:
        zero = 0 in (float(pair.group(1)), float(pair.group(2)))
        return "unilateral" if zero else "bilateral_unequal"
    if RANGE.search(raw) or re.search(r"\d/\d", raw):
        return "limits"
    if re.fullmatch(r"\(.*\)", raw):
        return "reference"
    return "basic"


def _is_note(raw: str) -> bool:
    words = re.findall(r"[A-Za-z]{3,}", QUANTITY.sub("", raw))
    numbers = re.findall(r"\d*\.\d+|\d+(?![X\d])", QUANTITY.sub("", raw))
    real = [w for w in words if w.upper() not in WORDS_THAT_ARE_NOT_NOTES]
    return bool(real) and not any("." in n for n in numbers)


def _frame_cells(frames: list[dict[str, Any]]) -> set[str]:
    cells = set()
    for frame in frames:
        cells.add(_cell(_diameter(str(frame.get("tolerance") or ""))))
        cells |= {str(d).strip()[:1] for d in _list(frame.get("datums"))}
    return {c for c in cells if c}


def _cell(text: str) -> str:
    return re.sub(r"[^0-9A-Z.]", "", text.upper())


def _diameter(text: str) -> str:
    return re.sub(r"[Øø∅]", "⌀", text.strip())


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _number(value: Decimal | None) -> int | float | None:
    if value is None:
        return None
    return int(value) if value == value.to_integral() else float(value)
