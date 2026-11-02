import json
from pathlib import Path

import pymupdf

from resourcly.adapters.callout_locator import locate
from resourcly.adapters.vlm_readers import VectorCropReaderAdapter, WholePageReaderAdapter
from resourcly.bootstrap import PROJECT_ROOT
from resourcly.models import ReadProgress, validate_document
from tests.conftest import CTC01

DRAWINGS = PROJECT_ROOT / "data" / "drawings"
PNG = b"\x89PNG\r\n\x1a\n"


class FakeModel:
    """Answers every prompt with the next canned answer, and records what it was asked."""

    def __init__(self, *answers: str):
        self.answers = list(answers)
        self.calls: list[tuple[str, list[bytes], int]] = []

    def generate(self, prompt: str, images: list[bytes], max_tokens: int) -> str:
        self.calls.append((prompt, images, max_tokens))
        return self.answers[min(len(self.calls), len(self.answers)) - 1]


def _answer(lines=(), frames=()) -> str:
    return json.dumps({"lines": list(lines), "feature_control_frames": list(frames)})


def test_the_crop_reader_asks_once_per_callout_with_a_png_crop() -> None:
    with pymupdf.open(DRAWINGS / f"{CTC01}.pdf") as pdf:
        callouts = len(locate(pdf[0]))
    model = FakeModel(_answer(["Ø25 ±0.15"]))

    VectorCropReaderAdapter(DRAWINGS, model, prompt="read it", max_tokens=99).read(CTC01)

    assert len(model.calls) == callouts
    assert all(prompt == "read it" and tokens == 99 for prompt, _, tokens in model.calls)
    assert all(len(images) == 1 and images[0].startswith(PNG) for _, images, _ in model.calls)


def test_the_crop_reader_returns_a_valid_document_with_values_features_and_text() -> None:
    frame = {"symbol_name": "position", "tolerance": "0.75", "datums": ["A", "B", "C"]}
    model = FakeModel(_answer(["Ø25 ±0.15"], [frame]))

    document = VectorCropReaderAdapter(DRAWINGS, model, prompt="p").read(CTC01).document

    valid, issues = validate_document(document, gold=False)
    assert valid is not None, issues
    values = document["values"]
    dimension = next(v for v in values if v["callout"] == "dimension")
    assert (dimension["raw"], dimension["value"], dimension["unit"]) == ("⌀25 ±0.15", 25, "mm")
    assert dimension["limits"] == {"lower": 24.85, "upper": 25.15}
    assert {v["callout"] for v in values} >= {"feature_control_frame", "title_block"}
    features = {f["id"]: f for f in document["features"]}
    assert features[dimension["feature_id"]]["type"] == "hole"
    assert document["title_block"]["units"] == "mm"


def test_the_crop_reader_reads_the_same_frame_in_two_boxes_once() -> None:
    frame = {"symbol_name": "flatness", "tolerance": "0.2", "datums": []}
    document = (
        VectorCropReaderAdapter(DRAWINGS, FakeModel(_answer([], [frame])), "p").read(CTC01).document
    )

    frames = [v for v in document["values"] if v["callout"] == "feature_control_frame"]
    # every box says the same thing, but only boxes close to each other are merged
    assert 1 < len(frames) < 21


def test_a_crop_answer_that_is_not_json_reads_as_nothing_and_is_an_issue() -> None:
    with pymupdf.open(DRAWINGS / f"{CTC01}.pdf") as pdf:
        callouts = len(locate(pdf[0]))

    output = VectorCropReaderAdapter(DRAWINGS, FakeModel("I cannot read this"), "p").read(CTC01)

    assert {v["callout"] for v in output.document["values"]} == {"title_block"}
    assert [i.loc for i in output.answer_issues] == [
        ["answers", "page", 1, "callout", n] for n in range(1, callouts + 1)
    ]
    assert {i.message for i in output.answer_issues} == {"the crop answer has no JSON object"}


def test_a_crop_answer_of_the_wrong_shape_is_an_issue_naming_the_field() -> None:
    model = FakeModel(json.dumps({"lines": "Ø25 ±0.15", "feature_control_frames": []}))

    output = VectorCropReaderAdapter(DRAWINGS, model, "p").read(CTC01)

    assert output.answer_issues[0].message == "the crop answer: lines: Input should be a valid list"


def test_a_well_formed_read_has_no_answer_issues() -> None:
    frame = {"symbol_name": "position", "tolerance": "0.75", "datums": ["A", "B", "C"]}

    output = VectorCropReaderAdapter(DRAWINGS, FakeModel(_answer(["Ø25"], [frame])), "p").read(
        CTC01
    )

    assert output.answer_issues == []


def test_a_follow_up_answer_that_cannot_be_used_is_an_issue() -> None:
    unnamed = {"symbol_name": "", "tolerance": "1.5", "datums": ["A"]}
    model = FakeModel(_answer([], [unnamed]), "perpendicularity")
    reader = VectorCropReaderAdapter(DRAWINGS, model, "read", symbol_prompt="symbol?")

    output = reader.read(CTC01)

    first = output.answer_issues[0]  # later crops get the second answer as their crop answer
    assert (first.loc, first.message) == (
        ["answers", "page", 1, "callout", 1],
        "the symbol answer has no JSON object",
    )


def _page_answer(callouts, datums=()) -> str:
    return json.dumps({"callouts": callouts, "datum_feature_symbols": list(datums)})


def test_the_page_reader_asks_once_per_page_and_reads_every_callout() -> None:
    answer = _page_answer(
        [{"lines": ["Ø25 ±0.15"], "feature_control_frames": []}, {"lines": ["60° ±0.5°"]}],
        datums=["A", "B"],
    )
    model = FakeModel(answer)

    document = WholePageReaderAdapter(DRAWINGS, model, prompt="page", dpi=72).read(CTC01).document

    assert len(model.calls) == 1 and model.calls[0][1][0].startswith(PNG)
    raws = [v["raw"] for v in document["values"] if v["callout"] != "title_block"]
    assert raws == ["⌀25 ±0.15", "60° ±0.5°", "A", "B"]
    assert validate_document(document, gold=False)[1] == []


def test_the_page_reader_keeps_what_it_can_from_a_cut_off_loop() -> None:
    callout = json.dumps({"lines": ["⌀.025"], "feature_control_frames": []})
    looping = '{"callouts": [' + ", ".join([callout] * 40)  # stopped by the token limit
    first = json.dumps({"lines": ["Ø20 +0.05", "-0.10"]})
    model = FakeModel('{"callouts": [' + first + ", " + looping[len('{"callouts": [') :])

    document = WholePageReaderAdapter(DRAWINGS, model, prompt="page", dpi=72).read(CTC01).document

    raws = [v["raw"] for v in document["values"] if v["callout"] != "title_block"]
    assert raws == ["⌀20 +0.05/-0.10", "⌀.025"]


def test_a_cut_off_page_answer_and_a_callout_of_the_wrong_shape_are_issues() -> None:
    good = json.dumps({"lines": ["Ø20"]})
    bad = json.dumps({"lines": [None]})
    model = FakeModel('{"callouts": [' + good + ", " + bad + ", " + good)

    output = WholePageReaderAdapter(DRAWINGS, model, prompt="page", dpi=72).read(CTC01)

    assert [(i.loc, i.message) for i in output.answer_issues] == [
        (["answers", "page", 1], "the page answer is cut off; its complete callouts are kept"),
        (
            ["answers", "page", 1, "callout", 2],
            "the page answer: lines.0: Input should be a valid string",
        ),
    ]


def test_a_whole_page_answer_of_the_wrong_shape_keeps_its_callouts_and_says_why() -> None:
    model = FakeModel(json.dumps({"callouts": ["Ø20", {"lines": ["Ø8 ±0.1"]}]}))

    output = WholePageReaderAdapter(DRAWINGS, model, prompt="page", dpi=72).read(CTC01)

    raws = [v["raw"] for v in output.document["values"] if v["callout"] != "title_block"]
    assert raws == ["⌀8 ±0.1"]
    assert [i.message for i in output.answer_issues] == [
        "the page answer: callouts.0: Input should be a valid dictionary"
    ]


def test_an_empty_answer_for_a_datum_box_asks_for_its_letter() -> None:
    model = FakeModel(_answer(), '{"letter": "A"}')
    reader = VectorCropReaderAdapter(DRAWINGS, model, "read", letter_prompt="letter?")

    document = reader.read(CTC01).document

    letters = [p for p, _, _ in model.calls if p == "letter?"]
    datums = [v["raw"] for v in document["values"] if v["callout"] == "datum_feature_symbol"]
    assert len(letters) == 3  # the A, B and C boxes on CTC-01
    assert datums == ["A", "A", "A"]


def test_a_frame_without_a_named_symbol_asks_for_the_symbol() -> None:
    unnamed = {"symbol_name": "", "tolerance": "1.5", "datums": ["A"]}
    model = FakeModel(_answer([], [unnamed]), '{"symbol_name": "perpendicularity"}')
    reader = VectorCropReaderAdapter(DRAWINGS, model, "read", symbol_prompt="symbol?")

    document = reader.read(CTC01).document

    frame = next(v for v in document["values"] if v["callout"] == "feature_control_frame")
    assert (frame["raw"], frame["kind"]) == ("⊥ 1.5 | A", "perpendicularity")


def test_a_reading_whose_numbers_do_not_parse_is_written_without_a_tolerance() -> None:
    frame = {"symbol_name": "position", "tolerance": "±.020", "datums": ["A"]}
    model = FakeModel(_answer(["2X Ø.562 ±."], [frame]))

    document = VectorCropReaderAdapter(DRAWINGS, model, prompt="p").read(CTC01).document

    toleranced = {"limits", "plus_minus", "unilateral", "bilateral_unequal", "geometric_zone"}
    unparsed = [v for v in document["values"] if v["raw"] in ("⌖ ±.020 | A", "2X ⌀.562 ±.")]
    assert unparsed
    assert all(v["value"] is None and v["tolerance_style"] not in toleranced for v in unparsed)
    assert all(v["callout"] == "note" for v in unparsed if v["raw"].startswith("⌖"))
    assert validate_document(document, gold=False)[1] == []


def test_the_crop_reader_reports_each_callout_before_it_reads_it() -> None:
    with pymupdf.open(DRAWINGS / f"{CTC01}.pdf") as pdf:
        callouts = len(locate(pdf[0]))
    model = FakeModel(_answer(["Ø25 ±0.15"]))
    seen = []

    def report(progress: ReadProgress) -> None:
        seen.append((progress, len(model.calls)))

    VectorCropReaderAdapter(DRAWINGS, model, prompt="p").read(CTC01, progress=report)

    assert [(p.done, calls) for p, calls in seen] == [(n, n) for n in range(callouts + 1)]
    assert all((p.page, p.pages, p.total) == (1, 1, callouts) for p, _ in seen)
    first, third, last = seen[0][0], seen[2][0], seen[-1][0]
    assert third.page_done == 2 and len(third.boxes) == callouts
    assert all(0 <= edge <= 1 for box in third.boxes for edge in box)
    # Each report after the first names what the callout before it read.
    assert first.latest == [] and third.latest == ["⌀25 ±0.15"]
    assert (last.page_done, last.latest) == (callouts, ["⌀25 ±0.15"])


def test_the_page_reader_reports_each_page_before_it_reads_it() -> None:
    seen: list[ReadProgress] = []

    WholePageReaderAdapter(DRAWINGS, FakeModel(_page_answer([])), "page", dpi=36).read(
        "nist_ftc_06_asme1_rd", progress=seen.append
    )

    assert [(p.page, p.pages, p.done, p.total) for p in seen] == [
        (1, 3, 0, 3),
        (2, 3, 1, 3),
        (3, 3, 2, 3),
    ]


def _raster_copy(drawing: str, folder: Path) -> str:
    """The drawing's first page as a picture in a one-page PDF, as an image upload is stored."""
    with pymupdf.open(DRAWINGS / f"{drawing}.pdf") as pdf:
        picture = pdf[0].get_pixmap(dpi=100).tobytes("png")
    with pymupdf.open() as raster:
        page = raster.new_page(width=792, height=612)
        page.insert_image(page.rect, stream=picture)
        raster.save(folder / "raster.pdf")
    return "raster"


def test_a_page_with_no_vector_callouts_is_read_whole(tmp_path: Path) -> None:
    drawing = _raster_copy(CTC01, tmp_path)
    model = FakeModel(_page_answer([{"lines": ["Ø25 ±0.15"]}], datums=["A"]))
    reader = VectorCropReaderAdapter(tmp_path, model, prompt="crop", page_prompt="page")
    seen: list[ReadProgress] = []

    document = reader.read(drawing, progress=seen.append).document

    assert [prompt for prompt, _, _ in model.calls] == ["page"]
    assert [v["raw"] for v in document["values"]] == ["⌀25 ±0.15", "A"]
    assert {tuple(v["bbox"]) for v in document["values"]} == {(0.0, 0.0, 1.0, 1.0)}
    features = {f["id"]: f for f in document["features"]}
    described = {features[v["feature_id"]]["description"] for v in document["values"]}
    assert described == {
        "Read from the whole page, which has no vector callouts (a scan or an image)."
    }
    assert [(p.done, p.total) for p in seen] == [(0, 1), (1, 1)]
    assert validate_document(document, gold=False)[1] == []


def test_a_page_with_vector_callouts_never_needs_the_whole_page() -> None:
    model = FakeModel(_answer(["Ø25 ±0.15"]))

    VectorCropReaderAdapter(DRAWINGS, model, prompt="crop", page_prompt="page").read(CTC01)

    assert {prompt for prompt, _, _ in model.calls} == {"crop"}


def test_without_a_page_prompt_a_raster_page_reads_as_nothing(tmp_path: Path) -> None:
    drawing = _raster_copy(CTC01, tmp_path)
    model = FakeModel(_page_answer([{"lines": ["Ø25 ±0.15"]}]))

    document = VectorCropReaderAdapter(tmp_path, model, prompt="crop").read(drawing).document

    assert model.calls == [] and document["values"] == []
