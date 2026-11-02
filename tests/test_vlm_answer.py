from io import BytesIO

import pytest
from PIL import Image

from resourcly.adapters.vlm_answer import VlmPhotoAnswerAdapter
from resourcly.models import Attachment, DraftAction, DraftFinding, PhotoEvidence
from tests.conftest import png
from tests.test_photo_answers import EVIDENCE

PROMPT = (
    "Answer from this.\n<evidence>\n{evidence}\n</evidence>\n<question>\n{question}\n</question>"
)
ANSWER = """```json
{"image_type": "fracture_surface_closeup", "match": true, "what_is_wrong": "Fatigue at the holes.",
 "findings": [{"statement": "Origins at the holes.", "source": "[18-061 fig05]"}],
 "actions": [{"action": "Check the bolts.", "basis": "stated", "source": "18-061 p3",
              "quote": "torque was measured"},
             {"action": "Inspect the other wing.", "basis": "inferred", "source": ""}]}
```"""


class FakeModel:
    model_id = "org/vlm"
    revision = "abc123"

    def __init__(self, answer: str = ANSWER):
        self.answer = answer
        self.calls: list[tuple[str, list[bytes], int]] = []

    def generate(self, prompt: str, images: list[bytes], max_tokens: int) -> str:
        self.calls.append((prompt, images, max_tokens))
        return self.answer


def evidence(question: str = "Why did it crack?") -> PhotoEvidence:
    figures = [EVIDENCE.figure(name) for name in ("18-061/fig05", "18-061/fig06", "24-013/fig03")]
    return PhotoEvidence(
        question=question,
        photo=Attachment("crack.png", "image/png", png(2000, 1000)),
        figures=figures,
        images=[EVIDENCE.figure_image(f.figure, 100) for f in figures[:2]],
        reports=[EVIDENCE.report("18-061"), EVIDENCE.report("24-013")],
    )


def test_the_model_sees_the_photo_then_the_figure_images() -> None:
    model = FakeModel()
    shown = evidence()

    VlmPhotoAnswerAdapter(model, PROMPT, max_tokens=500, photo_side=1024).answer(shown)

    [(_, images, max_tokens)] = model.calls
    assert max_tokens == 500
    assert len(images) == 3
    assert Image.open(BytesIO(images[0])).size == (1024, 512)
    assert images[1:] == shown.images


def test_the_prompt_holds_the_question_and_every_source_with_its_labels() -> None:
    model = FakeModel()

    VlmPhotoAnswerAdapter(model, PROMPT, max_tokens=500, paragraph_chars=120).answer(evidence())

    prompt = model.calls[0][0]
    assert prompt.startswith("Answer from this.")
    assert "<question>\nWhy did it crack?\n</question>" in prompt
    assert "[18-061 fig05] reference image 1; section spar_fatigue_N106ER, failure mode" in prompt
    assert "[24-013 fig03] not shown as an image;" in prompt
    assert "Caption: Figure 5. Closer views of the fracture surfaces" in prompt
    assert "[18-061 p2] " in prompt and "[18-061 p9] " in prompt
    assert "Report 18-061: Piper PA-28R-201, N106ER; components examined:" in prompt
    longest = max(len(line) for line in prompt.splitlines() if line.startswith("[18-061 p"))
    assert longest <= len("[18-061 p2] ") + 120


def test_the_json_answer_becomes_a_draft_with_its_sources_as_written() -> None:
    model = FakeModel()

    draft = VlmPhotoAnswerAdapter(model, PROMPT, max_tokens=500).answer(evidence())

    assert (draft.matched, draft.image_type) == (True, "fracture_surface_closeup")
    assert draft.answer == "Fatigue at the holes."
    assert draft.findings == [DraftFinding("Origins at the holes.", "[18-061 fig05]")]
    assert draft.actions == [
        DraftAction("Check the bolts.", "stated", "18-061 p3", "torque was measured"),
        DraftAction("Inspect the other wing.", "inferred", "", ""),
    ]
    assert draft.text == ANSWER


def test_an_answer_that_is_not_json_is_an_error() -> None:
    adapter = VlmPhotoAnswerAdapter(FakeModel("I think it is fatigue."), PROMPT, max_tokens=500)

    with pytest.raises(ValueError, match="not the JSON the prompt asks for"):
        adapter.answer(evidence())


def test_malformed_entries_are_skipped_and_a_missing_match_is_no_match() -> None:
    model = FakeModel(
        '{"what_is_wrong": "Unclear.", "findings": ["x", {"statement": "y"}],'
        ' "actions": [{"action": "z"}, 3]}'
    )

    draft = VlmPhotoAnswerAdapter(model, PROMPT, max_tokens=500).answer(evidence())

    assert (draft.matched, draft.image_type) == (False, "")
    assert draft.findings == [DraftFinding("y", "")]
    assert draft.actions == [DraftAction("z", "inferred", "", "")]


def test_the_trace_names_the_model_and_its_snapshot() -> None:
    adapter = VlmPhotoAnswerAdapter(FakeModel(), PROMPT, max_tokens=500)

    assert adapter.called == "org/vlm (snapshot abc123), one answer from the photo and the figures"


@pytest.mark.parametrize(
    ("written", "matched"), [("true", True), ('"true"', True), ('"no"', False)]
)
def test_a_match_written_as_text_is_read(written: str, matched: bool) -> None:
    model = FakeModel(f'{{"match": {written}, "what_is_wrong": "x"}}')
    adapter = VlmPhotoAnswerAdapter(model, PROMPT, max_tokens=500)

    assert adapter.answer(evidence()).matched is matched


def test_an_action_that_repeats_the_prompt_is_dropped() -> None:
    prompt = f'{PROMPT}\nOtherwise set basis to "inferred" and leave quote empty.'
    model = FakeModel(
        '{"match": true, "what_is_wrong": "x", "actions": ['
        '{"action": "Set basis to \'inferred\' and leave quote empty.", "basis": "inferred"},'
        ' {"action": "Answer from this.", "basis": "inferred"},'
        ' {"action": "Replace the spar cap.", "basis": "inferred"}]}'
    )

    draft = VlmPhotoAnswerAdapter(model, prompt, max_tokens=500).answer(evidence())

    # "Answer from this." is too short to tell from an action the evidence gave
    assert [action.action for action in draft.actions] == [
        "Answer from this.",
        "Replace the spar cap.",
    ]
