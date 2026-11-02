"""Readers that show a drawing to a vision-language model and turn its answers into a document.

Both readers ask the model only to transcribe, in the shape `callout_values.readings` expects, and
leave the structure to code. Both read the title block and the notes from the PDF text layer,
exactly, so they differ only in how the model sees the callouts:

- `VectorCropReaderAdapter` finds each callout from the vector paths (`callout_locator`) and asks
  the model about one crop at a time. A page with no vector callouts, such as a scan or an image
  upload, is read whole instead when the version gives a `page_prompt`.
- `WholePageReaderAdapter` asks the model about the whole page at once.

Each answer is checked against its shape (`callout_values.Answer`) as soon as it comes back. One
with no JSON or of the wrong shape reads as nothing and is returned as an answer issue, so a person
sees it in the reading rather than a value that is just missing.

What each callout points at is not traced: each callout becomes one feature, typed by a fixed rule
on what it says (`callout_values.feature_type`).
"""

import json
import math
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from itertools import groupby
from pathlib import Path
from typing import Any

import pymupdf
from pydantic import ValidationError

from resourcly.adapters.callout_locator import Callout, Rect, locate
from resourcly.adapters.text_reader import text_records
from resourcly.callout_values import (
    Answer,
    LetterAnswer,
    PageAnswer,
    SymbolAnswer,
    Transcription,
    datum_letter,
    feature_type,
    name_symbols,
    needs_symbol,
    readings,
    sheet_units,
    value_fields,
)
from resourcly.errors import NotFound, UnreadableDrawing
from resourcly.models import Issue, ReaderOutput, ReadProgress, drawing_short
from resourcly.ports import Progress, VisionModelPort

Box = tuple[float, float, float, float]
WHOLE_PAGE: Box = (0.0, 0.0, 1.0, 1.0)
CALLOUT = "The feature this callout points at; the leader is not traced."
RASTER_PAGE = "Read from the whole page, which has no vector callouts (a scan or an image)."


@dataclass(frozen=True)
class Group:
    """The readings of one callout (or one model answer item), where it is, and on which page."""

    page: int
    box: Box
    readings: list[dict[str, Any]]
    description: str = CALLOUT


class VectorCropReaderAdapter:
    """Proposal 1: one crop per callout found from the vector paths, one model call per crop.

    Each crop is the callout's box plus `margin` points, rendered at `crop_dpi`, with the other
    callouts that fall in the margin painted out so the model reads only this one.

    Two follow-up questions are asked about the same crop when they are set. `symbol_prompt` is
    asked when a frame comes back with a tolerance but no characteristic named. `letter_prompt`
    is asked when a small frame with one letter in it (a datum feature box) reads as nothing.

    A page with no vector callouts, such as a scan or an image upload, has nothing to crop. With
    `page_prompt` set it is read whole, as `WholePageReaderAdapter` reads a page, and its features
    say so; without it the page gives no values.
    """

    def __init__(
        self,
        folder: Path,
        model: VisionModelPort,
        prompt: str,
        letter_prompt: str | None = None,
        symbol_prompt: str | None = None,
        crop_dpi: int = 300,
        margin: float = 4.0,
        max_tokens: int = 700,
        page_prompt: str | None = None,
        page_dpi: int = 150,
        page_max_tokens: int = 4000,
    ):
        self.folder = folder
        self.model = model
        self.prompt = prompt
        self.letter_prompt = letter_prompt
        self.symbol_prompt = symbol_prompt
        self.crop_dpi = crop_dpi
        self.margin = margin
        self.max_tokens = max_tokens
        self.page_prompt = page_prompt
        self.page_dpi = page_dpi
        self.page_max_tokens = page_max_tokens

    def read(self, drawing: str, progress: Progress | None = None) -> ReaderOutput:
        with _open(self.folder, drawing) as pdf:
            # Every page is located first, so the progress knows the drawing's step count: one
            # step per callout, and one per page read whole.
            located = [locate(page) for page in pdf]
            whole = [not callouts and self.page_prompt is not None for callouts in located]
            total = sum(map(len, located)) + sum(whole)
            groups: list[Group] = []
            issues: list[Issue] = []
            done = 0

            def report(page: pymupdf.Page, fractions: list[Box], page_done: int) -> None:
                if progress:
                    latest = [r["raw"] for r in groups[-1].readings] if groups else []
                    progress(
                        ReadProgress(
                            page=page.number + 1,
                            pages=pdf.page_count,
                            done=done,
                            total=total,
                            boxes=fractions,
                            page_done=page_done,
                            latest=latest,
                        )
                    )

            for page, callouts, read_whole in zip(pdf, located, whole, strict=True):
                if read_whole:
                    report(page, [], 0)
                    found, problems = page_groups(
                        self.model,
                        self.page_prompt,
                        page,
                        self.page_dpi,
                        self.page_max_tokens,
                        RASTER_PAGE,
                    )
                    groups += found
                    issues += problems
                    done += 1
                    if done == total:
                        report(page, [], 0)
                    continue
                if not callouts:
                    continue
                pixmap = page.get_pixmap(dpi=self.crop_dpi)
                fractions = [_fraction(c.box, page) for c in callouts]
                for index, callout in enumerate(callouts):
                    report(page, fractions, index)
                    others = [c.box for c in callouts if c.box is not callout.box]
                    image = crop_png(pixmap, callout.box, others, self.crop_dpi, self.margin)
                    found, problems = self._read_crop(image, callout)
                    groups.append(Group(page.number + 1, fractions[index], found))
                    where = ["answers", "page", page.number + 1, "callout", index + 1]
                    issues += [Issue(loc=where, message=problem) for problem in problems]
                    done += 1
                if done == total:
                    report(page, fractions, len(callouts))
            document = build_document(drawing, pdf, _merge_repeats(groups))
            return ReaderOutput(document=document, answer_issues=issues)

    def _read_crop(self, image: bytes, callout: Callout) -> tuple[list[dict[str, Any]], list[str]]:
        """The readings of one crop, and why each answer that could not be used was not."""
        problems: list[str] = []

        def ask[A: Answer](model: type[A], name: str, prompt: str, max_tokens: int) -> A | None:
            parsed, problem = parse_answer(model, self.model.generate(prompt, [image], max_tokens))
            if problem:
                problems.append(f"the {name} answer{problem}")
            return parsed

        transcription = ask(Transcription, "crop", self.prompt, self.max_tokens)
        transcription = transcription or Transcription(lines=[])
        if self.symbol_prompt and needs_symbol(transcription):
            symbol = ask(SymbolAnswer, "symbol", self.symbol_prompt, 40)
            if symbol:
                transcription = name_symbols(transcription, symbol.symbol_name)
        found = readings(transcription, framed=callout.framed, letters=callout.letters)
        if not found and self.letter_prompt and callout.framed and callout.letters <= 3:
            letter = ask(LetterAnswer, "letter", self.letter_prompt, 30)
            if letter and (found_letter := datum_letter(letter)):
                found = readings(Transcription(lines=[found_letter]), framed=True, letters=1)
        return found, problems


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

    def read(self, drawing: str, progress: Progress | None = None) -> ReaderOutput:
        with _open(self.folder, drawing) as pdf:
            groups: list[Group] = []
            issues: list[Issue] = []
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
                found, problems = page_groups(
                    self.model, self.prompt, page, self.dpi, self.max_tokens
                )
                groups += found
                issues += problems
            return ReaderOutput(document=build_document(drawing, pdf, groups), answer_issues=issues)


def page_groups(
    model: VisionModelPort,
    prompt: str,
    page: pymupdf.Page,
    dpi: int,
    max_tokens: int,
    description: str = CALLOUT,
) -> tuple[list[Group], list[Issue]]:
    """The callouts of one page from one model call about the whole page at `dpi`.

    Also returns an issue for an answer cut off before its end and for each callout in it of the
    wrong shape; the callouts that could be used are kept.
    """
    image = page.get_pixmap(dpi=dpi).tobytes("png")
    callouts, datums, problem = _page_answer(model.generate(prompt, [image], max_tokens))
    number = page.number + 1
    where: list[str | int] = ["answers", "page", number]
    issues = [Issue(loc=where, message=f"the page answer{problem}")] if problem else []
    found = []
    for index, callout in enumerate(_collapse(callouts), start=1):
        transcription, problem = parse_answer(Transcription, callout)
        if transcription:
            found.append(readings(transcription))
        else:
            issues.append(
                Issue(loc=[*where, "callout", index], message=f"the page answer{problem}")
            )
    found += [readings(Transcription(lines=[d]), framed=True, letters=1) for d in datums]
    return [Group(number, WHOLE_PAGE, r, description) for r in found], issues


def crop_png(
    pixmap: pymupdf.Pixmap, box: Rect, others: list[Rect], dpi: int, margin: float
) -> bytes:
    """The box plus a margin as PNG, with the other boxes in the margin painted white."""
    scale = dpi / 72

    def pixels(rect: Rect) -> pymupdf.IRect:
        found = pymupdf.IRect(
            math.floor(rect.x0 * scale),
            math.floor(rect.y0 * scale),
            math.ceil(rect.x1 * scale),
            math.ceil(rect.y1 * scale),
        )
        return found & pixmap.irect

    region = pixels(box.grown(margin))
    crop = pymupdf.Pixmap(pixmap.colorspace, region, pixmap.alpha)
    crop.copy(pixmap, region)
    for other in others:
        covered = pixels(other) & region
        if not covered.is_empty:
            crop.set_rect(covered, (255,) * pixmap.n)
    crop.copy(pixmap, pixels(box) & region)
    return crop.tobytes("png")


def parse_answer[A: Answer](
    model: type[A], answer: str | dict[str, Any]
) -> tuple[A | None, str | None]:
    """(the first JSON object in a model answer as `model`, None), or (None, why it is not one).

    The reason is worded to follow "the crop answer", such as " has no JSON object".
    """
    found = first_json(answer) if isinstance(answer, str) else answer
    if found is None:
        return None, " has no JSON object"
    try:
        return model.model_validate(found), None
    except ValidationError as error:
        details = [
            f"{'.'.join(map(str, d['loc'])) or 'answer'}: {d['msg'].removeprefix('Value error, ')}"
            for d in error.errors()
        ]
        return None, ": " + "; ".join(details)


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
                "description": group.description,
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


def _page_answer(text: str) -> tuple[list[dict[str, Any]], list[str], str | None]:
    """The callouts and datum letters of a whole-page answer, also from a cut-off answer.

    The third item says why the answer is not a whole page answer, or is None when it is one. An
    answer with no complete page object (the first object found is a callout) was cut off.
    """
    whole, problem = parse_answer(PageAnswer, text)
    if whole:
        return whole.callouts, whole.datum_feature_symbols, None
    start = text.find("[", text.find('"callouts"'))
    callouts = json_objects(text[start + 1 :]) if start > 0 else []
    first = first_json(text)
    if callouts and not (first and "callouts" in first):
        problem = " is cut off; its complete callouts are kept"
    return callouts, [], problem


def _collapse(callouts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep a callout repeated three or more times in a row once, the sign of a repetition loop."""
    kept: list[dict[str, Any]] = []
    for _, run in groupby(callouts, key=lambda c: json.dumps(c, sort_keys=True)):
        found = list(run)
        kept += found[:1] if len(found) >= 3 else found
    return kept


def _merge_repeats(groups: list[Group], max_gap: float = 0.03) -> list[Group]:
    """Drop a reading that a neighbouring box already gave, word for word.

    Boxes can overlap, so the same frame can be read from two crops. Two readings are one when
    they have the same callout and raw text and their boxes are within `max_gap` of the page.
    """
    kept: list[Group] = []
    for group in groups:
        fresh = [
            r
            for r in group.readings
            if not any(
                g.page == group.page
                and _gap(g.box, group.box) <= max_gap
                and any(k["callout"] == r["callout"] and k["raw"] == r["raw"] for k in g.readings)
                for g in kept
            )
        ]
        kept.append(Group(group.page, group.box, fresh, group.description))
    return kept


def _gap(a: Box, b: Box) -> float:
    return max(a[0] - b[2], b[0] - a[2], a[1] - b[3], b[1] - a[3], 0.0)


def _fraction(box: Rect, page: pymupdf.Page) -> Box:
    width, height = page.rect.width, page.rect.height
    return (
        max(box.x0 / width, 0.0),
        max(box.y0 / height, 0.0),
        min(box.x1 / width, 1.0),
        min(box.y1 / height, 1.0),
    )


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
