import re
from typing import Any

from resourcly.adapters.route_pictures import png
from resourcly.adapters.vlm_readers import first_json
from resourcly.models import AnswerDraft, DraftAction, DraftFinding, PhotoEvidence
from resourcly.ports import VisionModelPort


class VlmPhotoAnswerAdapter:
    """Answers about a photo with a local vision-language model, in one call.

    The model sees the photo (at most `photo_side` pixels on its long side), then the figure
    images, and a prompt whose `{evidence}` and `{question}` are filled in. The evidence lists each
    figure with its labels, caption and citing paragraphs, then each report with its closing
    paragraphs, every one under the source an answer cites, such as [18-061 p3]. A paragraph is cut
    to `paragraph_chars`. The model answers in JSON; an answer that is not JSON is an error. An
    action that repeats the prompt's own words, such as its rule for an inferred action, is
    dropped.
    """

    def __init__(
        self,
        model: VisionModelPort,
        prompt: str,
        max_tokens: int,
        photo_side: int = 1024,
        paragraph_chars: int = 700,
    ):
        self.model = model
        self.prompt = prompt
        self.max_tokens = max_tokens
        self.photo_side = photo_side
        self.paragraph_chars = paragraph_chars

    @property
    def called(self) -> str:
        return (
            f"{self.model.model_id} (snapshot {self.model.revision}),"
            " one answer from the photo and the figures"
        )

    def answer(self, evidence: PhotoEvidence) -> AnswerDraft:
        prompt = self.prompt.replace("{evidence}", self._evidence(evidence)).replace(
            "{question}", evidence.question
        )
        images = [png(evidence.photo, self.photo_side), *evidence.images]
        text = self.model.generate(prompt, images, self.max_tokens)
        data = first_json(text)
        if not isinstance(data, dict):
            raise ValueError(
                f"{self.model.model_id} gave an answer that is not the JSON the"
                f" prompt asks for: {text[:200]!r}"
            )
        findings = [
            DraftFinding(str(entry["statement"]), str(entry.get("source") or ""))
            for entry in _entries(data.get("findings"))
            if entry.get("statement")
        ]
        actions = [
            DraftAction(
                str(entry["action"]),
                str(entry.get("basis") or "inferred"),
                str(entry.get("source") or ""),
                str(entry.get("quote") or ""),
            )
            for entry in _entries(data.get("actions"))
            if entry.get("action") and not _repeats(str(entry["action"]), self.prompt)
        ]
        return AnswerDraft(
            matched=data.get("match") is True or str(data.get("match")).lower() == "true",
            answer=str(data.get("what_is_wrong") or ""),
            findings=findings,
            actions=actions,
            text=text,
            image_type=str(data.get("image_type") or ""),
        )

    def _evidence(self, evidence: PhotoEvidence) -> str:
        lines = []
        for number, figure in enumerate(evidence.figures, start=1):
            shown = (
                f"reference image {number}"
                if number <= len(evidence.images)
                else "not shown as an image"
            )
            lines.append(
                f"[{figure.source}] {shown}; section {figure.section},"
                f" failure mode {figure.failure_mode}"
            )
            lines.append(f"Caption: {figure.caption}")
            lines += [f"[{p.source}] {self._cut(p.text)}" for p in figure.citing]
        for report in evidence.reports:
            lines.append(
                f"Report {report.report}: {report.vehicle or 'vehicle not given'};"
                f" components examined: {report.components or 'not given'}"
            )
            lines += [f"[{p.source}] {self._cut(p.text)}" for p in report.closing]
        return "\n".join(lines)

    def _cut(self, text: str) -> str:
        if len(text) <= self.paragraph_chars:
            return text
        return text[: self.paragraph_chars - 1].rsplit(" ", 1)[0] + "…"


MIN_REPEATED_WORDS = 4  # fewer could be an action the evidence gave that the prompt also says


def _repeats(action: str, prompt: str) -> bool:
    """Whether the action's words, at least `MIN_REPEATED_WORDS` of them, run in the prompt."""
    words = _words(action)
    return len(words.split()) >= MIN_REPEATED_WORDS and f" {words} " in f" {_words(prompt)} "


def _words(text: str) -> str:
    return " ".join(re.findall(r"\w+", text.lower()))


def _entries(value: Any) -> list[dict[str, Any]]:
    return [entry for entry in value if isinstance(entry, dict)] if isinstance(value, list) else []
