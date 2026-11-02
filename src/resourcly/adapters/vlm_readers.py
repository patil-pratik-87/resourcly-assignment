"""Readers that show a drawing to a vision-language model and turn its answers into a document.

The reader asks the model only to transcribe, in the shape `callout_values.readings` expects, and
leaves the structure to code. It reads the title block and the notes from the PDF text layer,
exactly, so only the callouts come from the model:

- `WholePageReaderAdapter` asks the model about the whole page at once.

What each callout points at is not traced: each callout becomes one feature, typed by a fixed rule
on what it says (`callout_values.feature_type`).
"""

import json
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from itertools import groupby
from pathlib import Path
from typing import Any

import pymupdf

from resourcly.adapters.text_reader import text_records
from resourcly.callout_values import feature_type, readings, sheet_units, value_fields
from resourcly.errors import NotFound, UnreadableDrawing
from resourcly.models import ReadProgress, drawing_short
from resourcly.ports import Progress, VisionModelPort

Box = tuple[float, float, float, float]
WHOLE_PAGE: Box = (0.0, 0.0, 1.0, 1.0)


@dataclass(frozen=True)
class Group:
    """The readings of one callout (or one model answer item), where it is, and on which page."""

    page: int
    box: Box
    readings: list[dict[str, Any]]


class WholePageReaderAdapter:
    """Proposal 2, the baseline: the whole page at `dpi`, one model call per page.

    The model lists every callout on the sheet. An answer cut off by the token limit keeps the
    callouts that were complete, and a callout repeated three or more times in a row (a
    repetition loop) is kept once.
    """

    def __init__(
        self,
        folder: Path,
        model: VisionModelPort,
        prompt: str,
        dpi: int = 150,
        max_tokens: int = 4000,
    ):
        self.folder = folder
        self.model = model
        self.prompt = prompt
        self.dpi = dpi
        self.max_tokens = max_tokens

    def read(self, drawing: str, progress: Progress | None = None) -> dict[str, Any]:
        with _open(self.folder, drawing) as pdf:
            groups = []
            for page in pdf:
                if progress:
                    progress(
                        ReadProgress(
                            page=page.number + 1,
                            pages=pdf.page_count,
                            done=page.number,
                            total=pdf.page_count,
                        )
                    )
                image = page.get_pixmap(dpi=self.dpi).tobytes("png")
                answer = self.model.generate(self.prompt, [image], self.max_tokens)
                callouts, datums = _page_answer(answer)
                number = page.number + 1
                groups += [Group(number, WHOLE_PAGE, readings(c)) for c in _collapse(callouts)]
                groups += [
                    Group(number, WHOLE_PAGE, readings({"lines": [d]}, framed=True, letters=1))
                    for d in datums
                ]
            return build_document(drawing, pdf, groups)


def first_json(text: str) -> Any:
    """The first complete JSON object in a model answer, or None."""
    objects = json_objects(text)
    return objects[0] if objects else None


def json_objects(text: str) -> list[dict[str, Any]]:
    """Every complete top-level JSON object in the text, skipping the ones nested in another."""
    decoder = json.JSONDecoder()
    found, end = [], 0
    for match in re.finditer(r"\{", text):
        if match.start() < end:
            continue
        try:
            value, end = decoder.raw_decode(text, match.start())
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            found.append(value)
    return found


def build_document(drawing: str, pdf: pymupdf.Document, groups: list[Group]) -> dict[str, Any]:
    """The document in the gold schema's shape: callout values, then notes, then the title block."""
    text = [record for page in pdf for record in text_records(page)]
    notes = [record for record in text if record[1] == "note"]
    raws = [r["raw"] for group in groups for r in group.readings]
    units, units_source = sheet_units([record[2] for record in notes], raws)
    prefix = drawing_short(drawing) or "rec"
    features, values = [], []

    def add(fields: dict[str, Any], page: int, box: Box, feature_id: str | None) -> None:
        values.append(
            {
                "id": f"{prefix}-{len(values) + 1:02d}",
                "raw": fields["raw"],
                "callout": fields["callout"],
                "kind": fields["kind"],
                "tolerance_style": fields["tolerance_style"],
                "value": fields["value"],
                "unit": fields["unit"],
                "feature_id": feature_id,
                "applies_to": None,
                "datums": fields["datums"],
                "limits": fields["limits"],
                "meaning": _meaning(fields),
                "page": page,
                "bbox": [round(edge, 3) for edge in box],
                "confidence": fields["confidence"],
            }
        )

    for group in groups:
        if not group.readings:
            continue
        feature_id = f"callout_{len(features) + 1:02d}"
        features.append(
            {
                "id": feature_id,
                "type": feature_type(group.readings),
                "label": group.readings[0]["raw"],
                "description": "The feature this callout points at; the leader is not traced.",
                "page": group.page,
            }
        )
        for reading in group.readings:
            fields = {**reading, **value_fields(reading, units), "confidence": None}
            add(fields, group.page, group.box, feature_id)
    if notes:
        features.append(
            {
                "id": "part",
                "type": "other",
                "label": "the whole part",
                "description": "General notes apply to the part as a whole.",
                "page": 1,
            }
        )
    for page, callout, raw, box in [*notes, *(r for r in text if r[1] == "title_block")]:
        fields = {
            "raw": raw,
            "callout": callout,
            "kind": callout,
            "tolerance_style": "none",
            "value": None,
            "unit": None,
            "datums": [],
            "limits": None,
            "confidence": None,
        }
        add(fields, page, box, "part" if callout == "note" else None)
    revision = next(
        (m[1] for r in text if r[1] == "title_block" if (m := re.fullmatch(r"Rev (\w+)", r[2]))),
        None,
    )
    return {
        "drawing": drawing,
        "page_count": pdf.page_count,
        "title_block": {
            "revision": revision,
            "units": units,
            "units_source": units_source,
            "drawing_number": drawing,
        },
        "features": features,
        "values": values,
    }


def _meaning(fields: dict[str, Any]) -> str:
    unit = {"mm": " mm", "in": " in", "deg": " degrees"}.get(fields["unit"] or "", "")
    kind = fields["kind"].replace("_", " ")
    limits = fields["limits"]
    if fields["callout"] == "feature_control_frame" and limits:
        datums = ", ".join(fields["datums"])
        to = f", relative to datum {datums}" if datums else ""
        return f"{kind.capitalize()} within a {limits['upper']:g}{unit} tolerance zone{to}."
    if fields["callout"] == "dimension" and limits:
        return f"The {kind} must be between {limits['lower']:g} and {limits['upper']:g}{unit}."
    if fields["callout"] == "dimension" and fields["value"] is not None:
        return f"A {kind} of {fields['value']:g}{unit}."
    if fields["callout"] == "datum_feature_symbol":
        return f"Datum feature {fields['raw']}."
    if fields["callout"] == "datum_target":
        return f"Datum target {fields['raw']}."
    return f"Printed on the sheet: {fields['raw']}"


def _page_answer(text: str) -> tuple[list[dict[str, Any]], list[str]]:
    """The callouts and datum letters of a whole-page answer, also from a cut-off answer."""
    whole = first_json(text)
    if isinstance(whole, dict) and isinstance(whole.get("callouts"), list):
        datums = whole.get("datum_feature_symbols")
        letters = [str(d) for d in datums] if isinstance(datums, list) else []
        return [c for c in whole["callouts"] if isinstance(c, dict)], letters
    start = text.find("[", text.find('"callouts"'))
    return (json_objects(text[start + 1 :]) if start > 0 else []), []


def _collapse(callouts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep a callout repeated three or more times in a row once, the sign of a repetition loop."""
    kept: list[dict[str, Any]] = []
    for _, run in groupby(callouts, key=lambda c: json.dumps(c, sort_keys=True)):
        found = list(run)
        kept += found[:1] if len(found) >= 3 else found
    return kept


@contextmanager
def _open(folder: Path, drawing: str) -> Iterator[pymupdf.Document]:
    path = folder / f"{drawing}.pdf"
    if not path.is_file():
        raise NotFound(f"no drawing named {drawing}")
    try:
        pdf = pymupdf.open(path)
    except pymupdf.FileDataError as error:
        raise UnreadableDrawing(f"{path.name} is not a readable PDF") from error
    with pdf:
        yield pdf
