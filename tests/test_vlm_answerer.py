import pytest

from resourcly.adapters.vlm_answerer import VlmAnswerAdapter
from resourcly.bootstrap import Settings, load_version
from resourcly.models import Choice, Passage, SelectEvidence, TextEvidence


class FakeModel:
    model_id = "org/fake-vlm"
    revision = "abc123"

    def __init__(self, text: str = "", probabilities: dict[str, float] | None = None):
        self.text = text
        self.probabilities = probabilities or {"A": 0.9, "B": 0.1}
        self.calls: list[tuple[str, int, int]] = []
        self.choices: list[tuple[str, list[str]]] = []

    def generate(self, prompt: str, images: list[bytes], max_tokens: int) -> str:
        self.calls.append((prompt, len(images), max_tokens))
        return self.text

    def choose(self, prompt: str, images: list[bytes], options: list[str]) -> Choice:
        self.choices.append((prompt, options))
        return Choice(self.probabilities, 1.0)


def adapter(model: FakeModel) -> VlmAnswerAdapter:
    return VlmAnswerAdapter(
        model,
        select_prompt="Pick.\n{blocks}\nJSON please",
        write_prompt="Write.\n{blocks}",
        gate_prompt="Gate <message>{message}</message>",
        select_tokens=80,
        write_tokens=400,
    )


def test_select_shows_the_blocks_with_no_image_and_reads_the_cites_and_kind() -> None:
    model = FakeModel('Sure: {"cites": ["ctc01-02", 7], "kind": "Flatness"} done')

    selection = adapter(model).select(SelectEvidence("q", [], "<evidence>x</evidence>"))

    assert (selection.kind, selection.cites) == ("Flatness", ["ctc01-02", "7"])
    assert model.calls == [("Pick.\n<evidence>x</evidence>\nJSON please", 0, 80)]


def test_select_with_no_json_names_no_kind_and_cites_nothing() -> None:
    selection = adapter(FakeModel("I cannot tell.")).select(SelectEvidence("q", [], ""))

    assert (selection.kind, selection.cites, selection.text) == (None, [], "I cannot tell.")


def test_write_reads_each_statement_and_its_source() -> None:
    model = FakeModel(
        '{"not_in_reports": false, "answer": "At LC-1.", "statements":'
        ' [{"text": "Origins at LC-1.", "source": "18-061 p2"}, {"text": ""}, "junk"]}'
    )
    passage = Passage(report="18-061", page=2, text="Origins at LC-1.")

    draft = adapter(model).write(TextEvidence("q", [passage], "<evidence>"))

    assert (draft.not_in_reports, draft.answer) == (False, "At LC-1.")
    assert [(s.statement, s.source) for s in draft.statements] == [
        ("Origins at LC-1.", "18-061 p2")
    ]
    assert model.calls[0][1:] == (0, 400)


def test_write_that_is_not_json_is_an_error() -> None:
    with pytest.raises(ValueError, match="not the JSON"):
        adapter(FakeModel("The reports say...")).write(TextEvidence("q", [], ""))


def test_the_gate_is_the_probability_of_the_first_option() -> None:
    model = FakeModel(probabilities={"A": 0.88, "B": 0.12})

    assert adapter(model).gate("what is the tolerance?") == 0.88
    assert model.choices == [("Gate <message>what is the tolerance?</message>", ["A", "B"])]
    adapter(model).gate("")
    assert model.choices[1][0] == "Gate <message>(no text)</message>"


def test_the_select_version_loads_with_its_prompts() -> None:
    version = load_version(Settings(), "qa", "select-v1")

    assert version.impl == "vlm"
    assert "{blocks}" in version.params["select_prompt"]
    assert "{blocks}" in version.params["write_prompt"]
    assert "{message}" in version.params["gate_prompt"]
