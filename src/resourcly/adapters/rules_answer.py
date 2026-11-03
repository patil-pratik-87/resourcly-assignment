import re

from resourcly.models import DraftFinding, SelectEvidence, Selection, TextDraft, TextEvidence

QUESTION = re.compile(
    r"\?|^\s*(what|why|how|where|which|who|when|is|are|was|were|does|do|did|can|could|should"
    r"|explain|tell|compare|list|show|find)\b",
    re.I,
)
SENTENCE = re.compile(r"(?<=[.!?])\s+")


class RulesAnswerAdapter:
    """A model-free answerer, the floor a model must beat.

    It picks no value of a drawing and names no kind, so code answers from the question's words
    alone. A text answer is the first sentences of the best passage, citing it. A message asks
    for an answer when it has a question mark or starts with a question word.
    """

    called = "no model: the word list, and the best passage's first sentences"

    def __init__(self, sentences: int = 2):
        self.sentences = sentences

    def select(self, evidence: SelectEvidence) -> Selection:
        return Selection(kind=None, cites=[], text="")

    def write(self, evidence: TextEvidence) -> TextDraft:
        if not evidence.passages:
            return TextDraft(not_in_reports=True, answer="", statements=[], text="")
        best = evidence.passages[0]
        said = " ".join(SENTENCE.split(best.text)[: self.sentences])
        return TextDraft(
            not_in_reports=False, answer="", statements=[DraftFinding(said, best.source)], text=""
        )

    def gate(self, text: str) -> float:
        return 1.0 if QUESTION.search(text) else 0.0
