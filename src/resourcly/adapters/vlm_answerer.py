from typing import Any

from resourcly.adapters.vlm_readers import first_json
from resourcly.models import DraftFinding, SelectEvidence, Selection, TextDraft, TextEvidence
from resourcly.ports import VisionModelPort


class VlmAnswerAdapter:
    """Answers questions with a local vision-language model, one call per question, no image.

    `select` shows the model a drawing's values and asks which answer the question and what kind
    of value it asks about. `write` shows it report passages and asks for statements that each
    cite one. Each prompt's `{blocks}` is filled with the marked evidence, earlier turns and
    question. `gate` reads one token: A when the message sent with files asks for more than
    reading them, B when it does not. The model's words are never shown as they are: code checks
    what it cites and prints the values from the records.
    """

    def __init__(
        self,
        model: VisionModelPort,
        select_prompt: str,
        write_prompt: str,
        gate_prompt: str,
        select_tokens: int = 80,
        write_tokens: int = 400,
    ):
        self.model = model
        self.select_prompt = select_prompt
        self.write_prompt = write_prompt
        self.gate_prompt = gate_prompt
        self.select_tokens = select_tokens
        self.write_tokens = write_tokens

    @property
    def called(self) -> str:
        return f"{self.model.model_id} (snapshot {self.model.revision})"

    def select(self, evidence: SelectEvidence) -> Selection:
        prompt = self.select_prompt.replace("{blocks}", evidence.blocks)
        text = self.model.generate(prompt, [], self.select_tokens)
        data = first_json(text)
        data = data if isinstance(data, dict) else {}
        kind = str(data.get("kind") or "").strip() or None
        cites = data.get("cites")
        return Selection(
            kind=kind,
            cites=[str(cite) for cite in cites] if isinstance(cites, list) else [],
            text=text,
        )

    def write(self, evidence: TextEvidence) -> TextDraft:
        prompt = self.write_prompt.replace("{blocks}", evidence.blocks)
        text = self.model.generate(prompt, [], self.write_tokens)
        data = first_json(text)
        if not isinstance(data, dict):
            raise ValueError(
                f"{self.model.model_id} gave an answer that is not the JSON the"
                f" prompt asks for: {text[:200]!r}"
            )
        statements = [
            DraftFinding(str(entry["text"]), str(entry.get("source") or ""))
            for entry in _entries(data.get("statements"))
            if entry.get("text")
        ]
        return TextDraft(
            not_in_reports=data.get("not_in_reports") is True,
            answer=str(data.get("answer") or ""),
            statements=statements,
            text=text,
        )

    def gate(self, text: str) -> float:
        prompt = self.gate_prompt.replace("{message}", text.strip() or "(no text)")
        return self.model.choose(prompt, [], ["A", "B"]).probabilities["A"]


def _entries(value: Any) -> list[dict[str, Any]]:
    return [entry for entry in value if isinstance(entry, dict)] if isinstance(value, list) else []
