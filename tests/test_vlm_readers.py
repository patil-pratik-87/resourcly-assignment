import json

from resourcly.adapters.vlm_readers import WholePageReaderAdapter
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


def _page_answer(callouts, datums=()) -> str:
    return json.dumps({"callouts": callouts, "datum_feature_symbols": list(datums)})


def test_the_page_reader_asks_once_per_page_and_reads_every_callout() -> None:
    answer = _page_answer(
        [{"lines": ["Ø25 ±0.15"], "feature_control_frames": []}, {"lines": ["60° ±0.5°"]}],
        datums=["A", "B"],
    )
    model = FakeModel(answer)

    document = WholePageReaderAdapter(DRAWINGS, model, prompt="page", dpi=72).read(CTC01)

    assert len(model.calls) == 1 and model.calls[0][1][0].startswith(PNG)
    raws = [v["raw"] for v in document["values"] if v["callout"] != "title_block"]
    assert raws == ["⌀25 ±0.15", "60° ±0.5°", "A", "B"]
    assert validate_document(document, gold=False)[1] == []


def test_the_page_reader_keeps_what_it_can_from_a_cut_off_loop() -> None:
    callout = json.dumps({"lines": ["⌀.025"], "feature_control_frames": []})
    looping = '{"callouts": [' + ", ".join([callout] * 40)  # stopped by the token limit
    first = json.dumps({"lines": ["Ø20 +0.05", "-0.10"]})
    model = FakeModel('{"callouts": [' + first + ", " + looping[len('{"callouts": [') :])

    document = WholePageReaderAdapter(DRAWINGS, model, prompt="page", dpi=72).read(CTC01)

    raws = [v["raw"] for v in document["values"] if v["callout"] != "title_block"]
    assert raws == ["⌀20 +0.05/-0.10", "⌀.025"]


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
