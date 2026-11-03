"""Answering a photo of a part from the NTSB reports: what is wrong, and what to do.

The failure finder ranks the report figures by how close they are to the photo. When none is
close enough, the gate says the reports do not show this failure and no model is asked.
Otherwise the answerer is shown the closest figures, the paragraphs that cite them and their
reports' closing paragraphs, and answers the user's text, or what is wrong and what to do when
there is none. It also says what the photo is; one that shows no part is kept out, as the gate
would. Code then keeps only what cites that evidence: a finding whose source was not shown is
dropped, a match without a kept finding is given as no match, and an action is "stated" only
when it quotes, word for word, a report paragraph it cites. Both steps are traced under the
request id.
"""

import hashlib
import logging
import re
import time
from collections.abc import Collection
from typing import Any

from resourcly.models import (
    Action,
    AnswerDraft,
    Attachment,
    Citation,
    DraftAction,
    FigureMatch,
    Finding,
    Passage,
    PhotoAnswer,
    PhotoEvidence,
    TraceEvent,
)
from resourcly.ports import PhotoAnswererPort, ReportEvidencePort, TracePort
from resourcly.services import FailureService, now

log = logging.getLogger(__name__)

DEFAULT_QUESTION = "What is wrong with this part, and what should be done about it?"
NOT_IN_REPORTS = (
    "This failure is not in the three NTSB reports: no report figure is close enough to the"
    " photo, so they say nothing about it."
)
UNRELATED = "This photo does not show a part, so the three NTSB reports say nothing about it."
NO_MATCH = "The closest report figures do not show the failure in this photo."
NO_CITED = (
    "The answer cited nothing in the reports it was shown, so it is not given. The closest report"
    " figures are listed."
)
# What an answerer may take a photo for that no report can be about
NO_PART = ("unrelated", "technical_drawing")
MIN_QUOTE_WORDS = 3  # a stated action's quote, so a word or two cannot pass as support
# A source as an answer writes it: "18-061 fig05", "[18-061 Figure 5]", "18-061 p3", "18-061 page 3"
SOURCE = re.compile(r"(\d{2}-\d{3})\W*(?:fig(?:ure)?\.?\s*0*(\d+)|p(?:age)?\.?\s*(\d+))", re.I)


class PhotoAnswerService:
    def __init__(
        self,
        failures: FailureService,
        evidence: ReportEvidencePort,
        answerer: PhotoAnswererPort,
        trace: TracePort,
        answer_name: str,
        figures: int = 3,
        images: int = 2,
        figure_side: int = 768,
    ):
        self.failures = failures
        self.evidence = evidence
        self.answerer = answerer
        self.trace = trace
        self.answer_name = answer_name
        self.figures = figures  # the closest figures shown, with their text
        self.images = images  # the first of them shown as images too
        self.figure_side = figure_side

    def answer(
        self,
        photo: Attachment,
        text: str,
        request_id: str,
        exclude: Collection[str] = (),
        matches: list[FigureMatch] | None = None,
    ) -> PhotoAnswer:
        """The answer; the figures in `exclude` are left out, as if no report held them.

        The `matches` an earlier answer about the photo found are used again, when given, instead
        of searching the figures again.
        """
        if matches is None:
            matches = self.failures.find(photo, request_id=request_id, exclude=exclude).figures
        started, began = now(), time.perf_counter()
        step: dict[str, Any] = {"input": {}, "output": {}, "error": None}
        try:
            if not matches:
                step["called"] = "the gate; no figure is close enough"
                step["output"] = {"not_in_reports": True}
                return PhotoAnswer(
                    not_in_reports=True,
                    kept_out="gate",
                    matched=False,
                    answer=NOT_IN_REPORTS,
                    findings=[],
                    actions=[],
                )
            step["called"] = self.answerer.called
            evidence = self._evidence(photo, text, matches)
            step["input"] = {
                "figures": [figure.figure for figure in evidence.figures],
                "images": len(evidence.images),
                "reports": [report.report for report in evidence.reports],
                **_traced_question(text),
            }
            draft = self.answerer.answer(evidence)
            answer, dropped = _checked(draft, evidence, matches)
            step["output"] = {
                "image_type": draft.image_type,
                "kept_out": answer.kept_out,
                "matched": answer.matched,
                "findings": len(answer.findings),
                "actions": len(answer.actions),
                "stated": sum(1 for action in answer.actions if action.basis == "stated"),
                "dropped": dropped,
                "text": draft.text,
            }
            return answer
        except Exception as error:
            step["error"] = f"{type(error).__name__}: {error}"
            raise
        finally:
            self._record(request_id, step, started, began)

    def _evidence(self, photo: Attachment, text: str, matches: list[FigureMatch]) -> PhotoEvidence:
        top = matches[: self.figures]
        figures = [self.evidence.figure(match.figure) for match in top]
        reports = list(dict.fromkeys(figure.report for figure in figures))
        return PhotoEvidence(
            question=text.strip() or DEFAULT_QUESTION,
            photo=photo,
            figures=figures,
            images=[
                self.evidence.figure_image(match.figure, self.figure_side)
                for match in top[: self.images]
            ],
            reports=[self.evidence.report(report) for report in reports],
        )

    def _record(self, request_id: str, step: dict[str, Any], started: str, began: float) -> None:
        event = TraceEvent(
            request_id=request_id,
            step="answer.photo",
            called=f"answer {self.answer_name}: {step.get('called', self.answerer.called)}",
            input=step["input"],
            output=step["output"],
            error=step["error"],
            started_at=started,
            duration_ms=round((time.perf_counter() - began) * 1000, 1),
        )
        try:
            self.trace.record(event)
        except Exception:
            log.exception("could not record the trace of request %s", request_id)


def render_reply(answer: PhotoAnswer) -> str:
    """The answer as the text of a chat reply."""
    lines = [answer.answer]
    if answer.findings:
        lines += ["", "From the reports:"]
        lines += [f"- {f.statement} [{f.citation.source}]" for f in answer.findings]
    if answer.actions:
        lines += ["", "What to do:"]
        for action in answer.actions:
            basis = (
                f'stated in {action.citation.source}: "{action.quote}"'
                if action.basis == "stated" and action.citation
                else "inferred"
            )
            lines.append(f"- {action.action} ({basis})")
    if answer.figures:
        closest = ", ".join(
            f"{figure.figure.replace('/', ' ')} ({figure.score:.2f})"
            if figure.score is not None
            else figure.figure.replace("/", " ")
            for figure in answer.figures[:3]
        )
        lines += ["", f"Closest report figures: {closest}"]
    return "\n".join(lines)


def _checked(
    draft: AnswerDraft, evidence: PhotoEvidence, matches: list[FigureMatch]
) -> tuple[PhotoAnswer, list[str]]:
    """The draft with only what cites the evidence, and the sources it gave that were not shown."""
    if draft.image_type.strip().lower() in NO_PART:
        return PhotoAnswer(
            not_in_reports=True,
            kept_out="unrelated",
            matched=False,
            answer=UNRELATED,
            findings=[],
            actions=[],
        ), []
    if not draft.matched:
        return _unmatched(draft.answer.strip() or NO_MATCH, matches), []
    shown = _shown(evidence)
    dropped = []
    findings = []
    for finding in draft.findings:
        citation = _citation(finding.source, shown)
        if citation is None:
            dropped.append(finding.source)
        else:
            findings.append(Finding(statement=finding.statement, citation=citation))
    if not findings:
        return _unmatched(NO_CITED, matches), dropped
    return PhotoAnswer(
        not_in_reports=False,
        matched=True,
        answer=draft.answer.strip() or findings[0].statement,
        findings=findings,
        actions=[_action(action, shown) for action in draft.actions],
        figures=matches,
    ), dropped


def _unmatched(answer: str, matches: list[FigureMatch]) -> PhotoAnswer:
    return PhotoAnswer(
        not_in_reports=False, matched=False, answer=answer, findings=[], actions=[], figures=matches
    )


def _action(draft: DraftAction, shown: dict[str, tuple[Citation, list[str]]]) -> Action:
    """The action, stated only when it quotes a report paragraph it cites, word for word."""
    citation = _citation(draft.source, shown)
    quote = _flat(draft.quote).strip("\"'“”‘’ ")
    stated = (
        draft.basis.strip().lower().startswith("stated")
        and citation is not None
        and citation.figure is None
        and len(quote.split()) >= MIN_QUOTE_WORDS
        and any(quote.lower() in _flat(text).lower() for text in shown[citation.source][1])
    )
    return Action(
        action=draft.action,
        basis="stated" if stated else "inferred",
        citation=citation,
        quote=quote if stated else None,
    )


def _shown(evidence: PhotoEvidence) -> dict[str, tuple[Citation, list[str]]]:
    """Every source the answerer was shown, by its canonical form, such as 18-061 fig05, with
    the text of each paragraph cited by that source; a figure has none."""
    shown: dict[str, tuple[Citation, list[str]]] = {}

    def passage(found: Passage) -> None:
        citation = Citation(source=found.source, report=found.report, page=found.page)
        texts = shown.setdefault(found.source, (citation, []))[1]
        if found.text not in texts:
            texts.append(found.text)

    for figure in evidence.figures:
        shown[figure.source] = (
            Citation(
                source=figure.source, report=figure.report, page=figure.page, figure=figure.figure
            ),
            [],
        )
        for found in figure.citing:
            passage(found)
    for report in evidence.reports:
        for found in report.closing:
            passage(found)
    return shown


def _citation(source: str, shown: dict[str, tuple[Citation, list[str]]]) -> Citation | None:
    found = SOURCE.search(source)
    if found is None:
        return None
    report, figure, page = found.groups()
    key = f"{report} fig{int(figure):02d}" if figure else f"{report} p{int(page)}"
    return shown[key][0] if key in shown else None


def _flat(text: str) -> str:
    return " ".join(text.split())


def _traced_question(text: str) -> dict[str, Any]:
    """The user's text as the trace keeps it: its length and hash, never the words."""
    text = text.strip()
    if not text:
        return {"question": "default"}
    return {
        "question_chars": len(text),
        "question_sha256": hashlib.sha256(text.encode()).hexdigest(),
    }
