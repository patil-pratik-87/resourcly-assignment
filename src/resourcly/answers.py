"""Answering a photo of a part from the NTSB reports: what is wrong, and what to do.

The failure finder ranks the report figures by how close they are to the photo. When none is
close enough, the gate says the reports do not show this failure and no model is asked.
Otherwise the answerer is shown the closest figures, the paragraphs that cite them and their
reports' closing paragraphs, and answers the user's text, or what is wrong and what to do when
there is none. Code then keeps only what cites that evidence: a finding whose source was not shown
is dropped, and an action is "stated" only when it cites shown report text. Both steps are traced
under the request id.
"""

import hashlib
import logging
import re
import time
from typing import Any

from resourcly.models import (
    Action,
    AnswerDraft,
    Attachment,
    Citation,
    FigureMatch,
    Finding,
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
NO_MATCH = "The closest report figures do not show the failure in this photo."
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

    def answer(self, photo: Attachment, text: str, request_id: str) -> PhotoAnswer:
        matches = self.failures.find(photo, request_id=request_id).figures
        started, began = now(), time.perf_counter()
        step: dict[str, Any] = {"input": {}, "output": {}, "error": None}
        try:
            if not matches:
                step["called"] = "the gate; no figure is close enough"
                step["output"] = {"not_in_reports": True}
                return PhotoAnswer(
                    not_in_reports=True,
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
                f"stated in {action.citation.source}"
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
    if not draft.matched:
        answer = draft.answer.strip() or NO_MATCH
        return PhotoAnswer(
            not_in_reports=False,
            matched=False,
            answer=answer,
            findings=[],
            actions=[],
            figures=matches,
        ), []
    shown = _shown(evidence)
    dropped = []
    findings = []
    for statement, source in draft.findings:
        citation = _citation(source, shown)
        if citation is None:
            dropped.append(source)
        else:
            findings.append(Finding(statement=statement, citation=citation))
    actions = []
    for action, basis, source in draft.actions:
        citation = _citation(source or "", shown)
        stated = basis.strip().lower().startswith("stated") and citation is not None
        actions.append(
            Action(action=action, basis="stated" if stated else "inferred", citation=citation)
        )
    return PhotoAnswer(
        not_in_reports=False,
        matched=True,
        answer=draft.answer.strip() or NO_MATCH,
        findings=findings,
        actions=actions,
        figures=matches,
    ), dropped


def _shown(evidence: PhotoEvidence) -> dict[str, Citation]:
    """Every source the answerer was shown, by its canonical form, such as 18-061 fig05."""
    shown = {}
    for figure in evidence.figures:
        shown[figure.source] = Citation(
            source=figure.source, report=figure.report, page=figure.page, figure=figure.figure
        )
        for passage in figure.citing:
            shown[passage.source] = Citation(
                source=passage.source, report=passage.report, page=passage.page
            )
    for report in evidence.reports:
        for passage in report.closing:
            shown[passage.source] = Citation(
                source=passage.source, report=passage.report, page=passage.page
            )
    return shown


def _citation(source: str, shown: dict[str, Citation]) -> Citation | None:
    found = SOURCE.search(source)
    if found is None:
        return None
    report, figure, page = found.groups()
    key = f"{report} fig{int(figure):02d}" if figure else f"{report} p{int(page)}"
    return shown.get(key)


def _traced_question(text: str) -> dict[str, Any]:
    """The user's text as the trace keeps it: its length and hash, never the words."""
    text = text.strip()
    if not text:
        return {"question": "default"}
    return {
        "question_chars": len(text),
        "question_sha256": hashlib.sha256(text.encode()).hexdigest(),
    }
