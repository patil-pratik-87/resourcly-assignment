"""Answering a question about a drawing or the reports: code decides what is shown, from records."""

import json

import pytest

from resourcly.bootstrap import PROJECT_ROOT
from resourcly.models import DraftFinding, ItemRef, Passage, Selection, TextDraft
from resourcly.questions import (
    KINDS,
    NOT_IN_REPORTS,
    NOT_ON_DRAWING,
    QuestionService,
    decide,
    drawing_evidence,
    words_kind,
)
from tests.test_failure_finder import MemoryTrace

CTC01 = json.loads((PROJECT_ROOT / "outputs" / "nist_ctc_01_asme1_rd.json").read_text())
SOURCE = ItemRef("r1", "item-1")


class FakeAnswerer:
    called = "fake answerer"

    def __init__(self, selection: Selection | None = None, draft: TextDraft | None = None):
        self.selection = selection or Selection(kind=None, cites=[], text="")
        self.draft = draft
        self.selected: list = []
        self.written: list = []

    def select(self, evidence):
        self.selected.append(evidence)
        return self.selection

    def write(self, evidence):
        self.written.append(evidence)
        return self.draft

    def gate(self, text: str) -> float:
        return 1.0


class FakeSearch:
    def __init__(self, passages: list[Passage]):
        self.passages = passages
        self.queries: list[str] = []

    def search(self, query: str, k: int) -> list[Passage]:
        self.queries.append(query)
        return self.passages[:k]


def service(answerer: FakeAnswerer, passages: list[Passage] = ()) -> QuestionService:
    return QuestionService(answerer, FakeSearch(list(passages)), MemoryTrace(), "rules-v0 (rules)")


@pytest.mark.parametrize(
    ("question", "kind"),
    [
        ("What is the flatness tolerance?", "flatness"),
        ("What is the perpendicularity tolerance, and to which datum?", "perpendicularity"),
        ("What is the tolerance on the smaller hole near the right end?", "diameter"),
        ("What profile tolerance applies to the hexagonal boss?", "profile_of_a_surface"),
        ("What is the total runout?", "total_runout"),
        ("Is there a circular runout on it?", "circular_runout"),
        ("What radius do the fillets have?", "radius"),
        ("What revision is this drawing?", "title_block"),
        ("What units does this drawing use?", "note"),
        ("What angle is dimensioned?", "angular"),
        ("Tell me a story", None),
    ],
)
def test_the_word_list_names_the_kind_a_question_asks_about(question: str, kind: str) -> None:
    assert words_kind(question) == kind


def test_every_kind_the_words_name_is_a_kind_the_model_may_give() -> None:
    assert {words_kind(word) for word in ("flatness", "hole", "revision", "units")} <= set(KINDS)


def evidence(document: dict = CTC01, limit: int = 60):
    return drawing_evidence([(SOURCE, document, False)], "", limit)


def test_one_value_of_the_kind_asked_is_the_answer() -> None:
    decision = decide("angular", [], evidence())

    assert decision.outcome == "answer"
    assert [shown.key for shown in decision.shown] == ["ctc01-13"]


def test_several_values_of_the_kind_are_candidates_with_the_cited_ones_first() -> None:
    decision = decide("diameter", ["ctc01-09"], evidence())

    assert decision.outcome == "candidates"
    keys = [shown.key for shown in decision.shown]
    assert keys[0] == "ctc01-09"
    assert sorted(keys) == ["ctc01-01", "ctc01-06", "ctc01-08", "ctc01-09", "ctc01-10"] + [
        "ctc01-11",
        "ctc01-17",
    ]


def test_no_value_of_a_frame_kind_shows_every_frame_in_case_one_was_misread() -> None:
    decision = decide("perpendicularity", [], evidence())

    assert decision.outcome == "none"
    assert decision.frames
    assert {shown.record["callout"] for shown in decision.shown} == {"feature_control_frame"}
    assert len(decision.shown) == 6


def test_no_value_of_another_kind_shows_nothing() -> None:
    decision = decide("surface_texture", [], evidence())

    assert (decision.outcome, decision.shown, decision.frames) == ("none", [], False)


def test_a_title_block_or_note_answer_is_the_cited_record() -> None:
    assert [s.key for s in decide("title_block", ["ctc01-22"], evidence()).shown] == ["ctc01-22"]
    assert decide("title_block", [], evidence()).outcome == "none"
    assert decide(None, ["ctc01-22"], evidence()).outcome == "none"


def test_the_evidence_keeps_the_values_of_the_kind_asked_first_when_it_must_cut() -> None:
    kept = drawing_evidence([(SOURCE, CTC01, False)], "What is the flatness tolerance?", 3)

    assert [shown.key for shown in kept][:2] == ["ctc01-02", "ctc01-12"]
    assert len(kept) == 3


def test_two_documents_with_the_same_ids_get_keys_that_name_their_item() -> None:
    other = ItemRef("r1", "item-2")
    kept = drawing_evidence([(SOURCE, CTC01, False), (other, CTC01, False)], "", 100)

    keys = [shown.key for shown in kept]
    assert len(set(keys)) == len(keys) == 46
    assert "item-2:ctc01-02" in keys


def test_a_drawing_answer_is_printed_from_the_record_never_from_the_model() -> None:
    answerer = FakeAnswerer(Selection(kind="flatness", cites=["ctc01-02"], text="0.3 mm"))
    document = {**CTC01, "values": [v for v in CTC01["values"] if v["id"] != "ctc01-12"]}

    answer = service(answerer).drawing("What is the flatness?", [(SOURCE, document, False)], "q1")

    assert answer.outcome == "answer"
    assert "▱ 0.2" in answer.reply and "0.3" not in answer.reply
    [cited] = answer.citations
    assert (cited.kind, cited.ref, cited.item_id, cited.page) == ("value", "ctc01-02", "item-1", 1)
    assert cited.bbox == tuple(next(v for v in CTC01["values"] if v["id"] == "ctc01-02")["bbox"])
    assert answer.checked is True


def test_cited_ids_that_are_not_in_the_evidence_are_dropped() -> None:
    answerer = FakeAnswerer(Selection(kind="angular", cites=["ctc01-13", "ctc01-99"], text=""))

    answer = service(answerer).drawing("Which angle?", [(SOURCE, CTC01, False)], "q1")

    assert answer.dropped == ["ctc01-99"]
    assert [c.ref for c in answer.citations] == ["ctc01-13"]


def test_a_kind_the_model_does_not_name_falls_back_to_the_word_list() -> None:
    answerer = FakeAnswerer(Selection(kind="none", cites=[], text=""))

    answer = service(answerer).drawing("What angle is shown?", [(SOURCE, CTC01, False)], "q1")

    assert (answer.outcome, answer.kind) == ("answer", "angular")


def test_candidates_are_listed_for_a_tap_and_cite_nothing() -> None:
    answer = service(FakeAnswerer()).drawing(
        "What is the hole diameter?", [(SOURCE, CTC01, False)], "q1"
    )

    assert answer.outcome == "candidates"
    assert answer.citations == []
    assert len(answer.candidates) == 7
    assert "7 values" in answer.reply


def test_not_on_the_drawing_says_so_and_offers_the_frames_for_a_frame_kind() -> None:
    answer = service(FakeAnswerer()).drawing(
        "What is the perpendicularity?", [(SOURCE, CTC01, False)], "q1"
    )

    assert answer.outcome == "none"
    assert answer.reply.startswith(NOT_ON_DRAWING)
    assert len(answer.candidates) == 6
    assert "misread" in answer.reply


def test_values_read_from_a_picture_are_marked_so() -> None:
    answer = service(FakeAnswerer()).drawing("What angle?", [(SOURCE, CTC01, True)], "q1")

    assert answer.picture is True
    assert "read from a picture" in answer.reply


def test_each_step_is_traced_without_the_question_words() -> None:
    trace = MemoryTrace()
    answerer = FakeAnswerer(Selection(kind="angular", cites=["ctc01-13"], text="{}"))
    questions = QuestionService(answerer, FakeSearch([]), trace, "rules-v0 (rules)")

    questions.drawing("What angle is secret?", [(SOURCE, CTC01, False)], "q1")

    steps = {event.step: event for event in trace.find("q1")}
    assert list(steps) == ["answer.select", "answer.check"]
    assert steps["answer.select"].called == "qa rules-v0 (rules): fake answerer"
    assert steps["answer.select"].output["cites"] == ["ctc01-13"]
    assert "secret" not in json.dumps([e.model_dump() for e in trace.find("q1")])
    assert steps["answer.check"].output["outcome"] == "answer"


P4 = Passage(report="16-006", page=4, text="Corrosion was observed on the control tube interior.")
P2 = Passage(report="16-006", page=2, text="The throttle position was 74% of full open.")


def test_a_text_answer_keeps_only_statements_that_cite_a_passage_it_was_shown() -> None:
    draft = TextDraft(
        not_in_reports=False,
        answer="Corrosion inside the control tube.",
        statements=[
            DraftFinding("corrosion was on the tube interior.", "16-006 p4"),
            DraftFinding("It was salt water.", "16-006 p9"),
        ],
        text="{}",
    )
    answerer = FakeAnswerer(draft=draft)

    answer = service(answerer, [P4, P2]).text("Where was the corrosion?", "q1")

    assert answer.outcome == "answer"
    assert [c.ref for c in answer.citations] == ["16-006 p4"]
    assert answer.citations[0].quote == P4.text
    assert answer.citations[0].said == "Corrosion was on the tube interior."
    assert answer.dropped == ["16-006 p9"]
    assert "[16-006 p4]" in answer.reply and "salt" not in answer.reply


def test_a_text_answer_with_no_cited_statement_says_the_reports_do_not_say() -> None:
    draft = TextDraft(False, "Probably rain.", [DraftFinding("Rain.", "")], "{}")

    answer = service(FakeAnswerer(draft=draft), [P4]).text("What was the weather?", "q1")

    assert (answer.outcome, answer.reply, answer.citations) == ("none", NOT_IN_REPORTS, [])


def test_the_retrieval_query_adds_the_previous_user_turn() -> None:
    search = FakeSearch([P4])
    draft = TextDraft(True, "", [], "{}")
    questions = QuestionService(FakeAnswerer(draft=draft), search, MemoryTrace(), "v")

    questions.text("And where?", "q1", earlier=[("Was there corrosion?", "Yes.")])

    assert search.queries == ["And where? Was there corrosion?"]


def test_a_value_whose_box_is_the_whole_page_was_read_from_a_picture() -> None:
    whole = {
        **CTC01,
        "values": [{**v, "bbox": [0.0, 0.0, 1.0, 1.0]} for v in CTC01["values"]],
    }

    answer = service(FakeAnswerer()).drawing("What angle?", [(SOURCE, whole, False)], "q1")

    assert answer.picture is True
    assert answer.citations[0].bbox is None
    assert "read from a picture" in answer.reply
