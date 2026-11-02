from dataclasses import replace

import pytest

from resourcly.adapters.figure_index import FigureIndex, IndexedEvidenceAdapter
from resourcly.adapters.vlm_answer import VlmPhotoAnswerAdapter
from resourcly.answers import DEFAULT_QUESTION, PhotoAnswerService, render_reply
from resourcly.bootstrap import PROJECT_ROOT, Settings, open_services
from resourcly.models import AnswerDraft, Attachment, FigureMatch, PhotoEvidence
from resourcly.services import FailureService
from tests.conftest import png
from tests.test_failure_finder import FakeFinder, MemoryTrace

INDEX = FigureIndex.load(PROJECT_ROOT / "versions" / "failure" / "indexes" / "dinov2-base-v1.json")
EVIDENCE = IndexedEvidenceAdapter(INDEX, PROJECT_ROOT / "data" / "reports")
PHOTO = Attachment("crack.png", "image/png", png())


def match(figure: str, score: float = 0.8) -> FigureMatch:
    found = EVIDENCE.figure(figure)
    return FigureMatch(
        figure=figure,
        report=found.report,
        section=found.section,
        failure_mode=found.failure_mode,
        score=score,
    )


SPAR = [match("18-061/fig05", 0.83), match("18-061/fig06", 0.8), match("24-013/fig03", 0.7)]


class FakeAnswerer:
    called = "fake answerer"

    def __init__(self, draft: AnswerDraft | Exception):
        self.draft = draft
        self.seen: list[PhotoEvidence] = []

    def answer(self, evidence: PhotoEvidence) -> AnswerDraft:
        self.seen.append(evidence)
        if isinstance(self.draft, Exception):
            raise self.draft
        return self.draft


FATIGUE = AnswerDraft(
    matched=True,
    answer="Fatigue cracks grew from the attachment holes of the lower spar cap.",
    findings=[
        ("Fatigue origins were at the holes.", "[18-061 fig05]"),
        ("Beach marks spread from the origin.", "18-061 Figure 6"),
        ("The doublers had fatigue origins too.", "18-061 p3"),
        ("A made-up fact.", "18-061 fig29"),
        ("Another made-up fact.", ""),
    ],
    actions=[
        ("Measure the torque of the attachment bolts.", "stated", "[18-061 p3]"),
        ("Replace the spar.", "stated", "18-061 p30"),
        ("Inspect the other wing.", "inferred", None),
        ("Check the holes with eddy current.", "stated in the report", "18-061 fig05"),
    ],
    text="{...}",
)


def service(
    finder: FakeFinder, answerer: FakeAnswerer, trace: MemoryTrace | None = None
) -> PhotoAnswerService:
    trace = trace or MemoryTrace()
    return PhotoAnswerService(
        failures=FailureService(finder, trace, "base (fake)"),
        evidence=EVIDENCE,
        answerer=answerer,
        trace=trace,
        answer_name="photo (fake)",
        figures=3,
        images=2,
        figure_side=200,
    )


def test_a_photo_no_figure_is_close_to_is_not_in_the_reports_and_no_model_is_asked() -> None:
    trace = MemoryTrace()
    answerer = FakeAnswerer(FATIGUE)

    answer = service(FakeFinder([]), answerer, trace).answer(PHOTO, "", "r1")

    assert (answer.not_in_reports, answer.matched) == (True, False)
    assert answer.findings == answer.actions == answer.figures == []
    assert "not in the three NTSB reports" in answer.answer
    assert answerer.seen == []
    assert [event.step for event in trace.find("r1")] == ["failure.find", "answer.photo"]
    gate = trace.find("r1")[1]
    assert gate.output == {"not_in_reports": True}
    assert gate.called == "answer photo (fake): the gate; no figure is close enough"


def test_the_answerer_sees_the_closest_figures_their_reports_and_the_users_question() -> None:
    answerer = FakeAnswerer(FATIGUE)

    service(FakeFinder(SPAR), answerer).answer(PHOTO, "Why did the spar crack?", "r1")

    [seen] = answerer.seen
    assert seen.question == "Why did the spar crack?"
    assert seen.photo == PHOTO
    assert [figure.source for figure in seen.figures] == [
        "18-061 fig05",
        "18-061 fig06",
        "24-013 fig03",
    ]
    assert len(seen.images) == 2 and all(image.startswith(b"\x89PNG") for image in seen.images)
    assert [report.report for report in seen.reports] == ["18-061", "24-013"]


def test_without_text_the_question_is_what_is_wrong_and_what_to_do() -> None:
    answerer = FakeAnswerer(FATIGUE)

    service(FakeFinder(SPAR), answerer).answer(PHOTO, "  ", "r1")

    assert answerer.seen[0].question == DEFAULT_QUESTION


def test_only_findings_citing_the_evidence_are_kept_each_with_its_page_or_figure() -> None:
    answer = service(FakeFinder(SPAR), FakeAnswerer(FATIGUE)).answer(PHOTO, "", "r1")

    assert (answer.not_in_reports, answer.matched) == (False, True)
    assert answer.answer.startswith("Fatigue cracks grew")
    assert [(f.statement, f.citation.source) for f in answer.findings] == [
        ("Fatigue origins were at the holes.", "18-061 fig05"),
        ("Beach marks spread from the origin.", "18-061 fig06"),
        ("The doublers had fatigue origins too.", "18-061 p3"),
    ]
    figure, page = answer.findings[0].citation, answer.findings[2].citation
    assert (figure.report, figure.page, figure.figure) == ("18-061", 13, "18-061/fig05")
    assert (page.report, page.page, page.figure) == ("18-061", 3, None)
    assert answer.figures == SPAR


def test_an_action_is_stated_only_when_it_cites_report_text_it_was_shown() -> None:
    answer = service(FakeFinder(SPAR), FakeAnswerer(FATIGUE)).answer(PHOTO, "", "r1")

    assert [(a.action, a.basis, a.citation and a.citation.source) for a in answer.actions] == [
        ("Measure the torque of the attachment bolts.", "stated", "18-061 p3"),
        ("Replace the spar.", "inferred", None),
        ("Inspect the other wing.", "inferred", None),
        ("Check the holes with eddy current.", "stated", "18-061 fig05"),
    ]


def test_figures_that_do_not_show_the_photos_failure_give_no_findings() -> None:
    draft = AnswerDraft(False, "The figures show a different part.", [], [], "{}")

    answer = service(FakeFinder(SPAR), FakeAnswerer(draft)).answer(PHOTO, "", "r1")

    assert (answer.not_in_reports, answer.matched) == (False, False)
    assert answer.answer == "The figures show a different part."
    assert answer.findings == answer.actions == []
    assert answer.figures == SPAR


def test_the_answer_step_is_traced_with_what_it_was_shown_and_what_was_kept() -> None:
    trace = MemoryTrace()

    service(FakeFinder(SPAR), FakeAnswerer(FATIGUE), trace).answer(PHOTO, "Why?", "r1")

    find, step = trace.find("r1")
    assert (find.step, step.step) == ("failure.find", "answer.photo")
    assert step.called == "answer photo (fake): fake answerer"
    assert step.input["figures"] == ["18-061/fig05", "18-061/fig06", "24-013/fig03"]
    assert step.input["images"] == 2
    assert step.input["question_chars"] == 4
    assert "question" not in step.input
    assert step.output["matched"] is True
    assert (step.output["findings"], step.output["actions"], step.output["stated"]) == (3, 4, 2)
    assert step.output["dropped"] == ["18-061 fig29", ""]
    assert step.output["text"] == "{...}"


def test_a_failing_answerer_is_traced_and_raised() -> None:
    trace = MemoryTrace()

    with pytest.raises(RuntimeError, match="no GPU"):
        service(FakeFinder(SPAR), FakeAnswerer(RuntimeError("no GPU")), trace).answer(
            PHOTO, "", "r1"
        )

    assert trace.find("r1")[1].error == "RuntimeError: no GPU"


def test_the_reply_gives_the_answer_its_cited_findings_marked_actions_and_figures() -> None:
    answer = service(FakeFinder(SPAR), FakeAnswerer(FATIGUE)).answer(PHOTO, "", "r1")

    reply = render_reply(answer)

    assert reply.splitlines()[0].startswith("Fatigue cracks grew")
    assert "- Fatigue origins were at the holes. [18-061 fig05]" in reply
    assert "- Measure the torque of the attachment bolts. (stated in 18-061 p3)" in reply
    assert "- Inspect the other wing. (inferred)" in reply
    assert "Closest report figures: 18-061 fig05 (0.83), 18-061 fig06 (0.80)" in reply


def test_the_default_answer_shares_the_readers_model_and_loads_nothing(settings: Settings) -> None:
    defaults = Settings().versions
    with open_services(replace(settings, versions={**defaults, "router": "stub-v0"})) as services:
        answers = services.photo_answers
        reader_model = services.drawings.reader.model

    assert isinstance(answers.answerer, VlmPhotoAnswerAdapter)
    assert answers.answerer.model is reader_model
    assert answers.answerer.model.revision == "not loaded"
    assert answers.answerer.prompt.lstrip().startswith("You are a failure-analysis assistant")
    assert (answers.figures, answers.images, answers.figure_side) == (3, 2, 768)
    assert services.failures.finder.encoder.revision == "not loaded"
    assert services.answer_name == "photo-v1 (vlm)"
