import pytest

from resourcly.eval_harness.metrics import score_answer, summarise_answers

PHOTO = {
    "kind": "positive",
    "expected_report": "18-061",
    "expected_figure": "18-061/fig06",
    "failure_mode": "fatigue",
    "failure_keywords": ["fatigue", "beach mark"],
}
NEGATIVE = {"kind": "negative_unrelated", "expected_report": "none"}
FIGURES = [
    {"figure": "18-061/fig05", "report": "18-061", "section": "s", "failure_mode": "fatigue"},
    {"figure": "24-013/fig03", "report": "24-013", "section": "t", "failure_mode": "overstress"},
]


def cite(source: str, report: str, page: int, figure: str | None = None) -> dict:
    return {"source": source, "report": report, "page": page, "figure": figure}


def answer(text: str, *citations: dict, matched: bool = True, actions=()) -> dict:
    return {
        "not_in_reports": False,
        "matched": matched,
        "answer": text,
        "findings": [{"statement": f"Fact {n}.", "citation": c} for n, c in enumerate(citations)],
        "actions": list(actions),
        "figures": FIGURES,
    }


GOOD = answer(
    "Fatigue cracks grew from the bolt holes.",
    cite("18-061 fig05", "18-061", 13, "18-061/fig05"),
    cite("18-061 p3", "18-061", 3),
)


def test_an_answer_citing_the_right_report_and_naming_the_mode_is_correct() -> None:
    assert score_answer(PHOTO, GOOD) == {
        "case_score": 1.0,
        "correct": 1.0,
        "matched": True,
        "report_cited": 1.0,
        "mode_named": 1.0,
        "citations": 2,
        "valid_citations": 2,
    }


@pytest.mark.parametrize(
    ("text", "named"),
    [
        ("Beach marks spread from the origin.", 1.0),
        ("The spar shows FATIGUE.", 1.0),
        ("It broke in overstress.", 0.0),
        ("Antifatigue paint.", 0.0),  # a keyword must start a word
    ],
)
def test_the_mode_is_named_when_a_keyword_starts_a_word(text: str, named: float) -> None:
    found = answer(text, cite("18-061 p3", "18-061", 3))

    assert score_answer(PHOTO, found)["mode_named"] == named


def test_a_finding_names_the_mode_too() -> None:
    found = answer("Cracks.", cite("18-061 p3", "18-061", 3))
    found["findings"][0]["statement"] = "Fatigue striations were found."

    assert score_answer(PHOTO, found)["mode_named"] == 1.0


def test_an_answer_citing_only_another_report_is_wrong() -> None:
    found = answer("Fatigue.", cite("24-013 fig03", "24-013", 5, "24-013/fig03"))

    scores = score_answer(PHOTO, found)

    assert (scores["report_cited"], scores["correct"]) == (0.0, 0.0)


@pytest.mark.parametrize(
    "citation",
    [
        cite("18-061 fig06", "18-061", 14, "18-061/fig06"),  # not a figure it was given
        cite("18-061 fig05", "24-013", 13, "18-061/fig05"),  # the figure is of another report
        cite("18-061 fig07", "18-061", 13, "18-061/fig05"),  # the source names another figure
        cite("16-006 p2", "16-006", 2),  # a page of a report none of its figures is from
        cite("18-061 p4", "18-061", 3),  # the source names another page
    ],
)
def test_a_citation_is_valid_only_for_a_figure_it_was_given_or_their_reports(
    citation: dict,
) -> None:
    found = answer("Fatigue.", cite("18-061 p3", "18-061", 3), citation)

    scores = score_answer(PHOTO, found)

    assert (scores["citations"], scores["valid_citations"], scores["correct"]) == (2, 1, 0.0)


def test_an_actions_citation_counts_and_can_cite_the_report() -> None:
    action = {
        "action": "Inspect.",
        "basis": "stated",
        "citation": cite("18-061 p3", "18-061", 3),
        "quote": "inspect the spar caps",
    }
    found = answer("Fatigue.", actions=[action, {"action": "Look.", "basis": "inferred"}])

    scores = score_answer(PHOTO, found)

    assert (scores["citations"], scores["valid_citations"], scores["report_cited"]) == (1, 1, 1.0)


@pytest.mark.parametrize(
    ("citation", "quote"),
    [
        (cite("18-061 p3", "18-061", 3), None),  # no quote
        (cite("18-061 p3", "18-061", 3), "inspect it"),  # too short to support it
        (cite("18-061 fig05", "18-061", 13, "18-061/fig05"), "inspect the spar caps"),  # a figure
    ],
)
def test_a_stated_action_must_quote_a_report_page_it_cites(citation: dict, quote) -> None:
    action = {"action": "Inspect.", "basis": "stated", "citation": citation, "quote": quote}
    found = answer("Fatigue.", cite("18-061 p3", "18-061", 3), actions=[action])

    scores = score_answer(PHOTO, found)

    assert (scores["citations"], scores["valid_citations"], scores["correct"]) == (2, 1, 0.0)


def test_an_inferred_action_may_cite_a_figure_without_a_quote() -> None:
    action = {
        "action": "Inspect.",
        "basis": "inferred",
        "citation": cite("18-061 fig05", "18-061", 13, "18-061/fig05"),
    }
    found = answer("Fatigue.", cite("18-061 p3", "18-061", 3), actions=[action])

    assert score_answer(PHOTO, found)["correct"] == 1.0


def test_a_photo_the_model_says_does_not_match_is_wrong() -> None:
    refused = answer("The figures show a different part.", matched=False)

    assert score_answer(PHOTO, refused)["correct"] == 0.0


def test_a_photo_answer_that_is_not_a_match_is_wrong_even_with_good_findings() -> None:
    assert score_answer(PHOTO, {**GOOD, "matched": False})["correct"] == 0.0


def test_a_failed_call_scores_nothing() -> None:
    assert score_answer(PHOTO, None) == {
        "case_score": 0.0,
        "correct": 0.0,
        "matched": None,
        "report_cited": 0.0,
        "mode_named": 0.0,
        "citations": 0,
        "valid_citations": 0,
    }
    assert score_answer(NEGATIVE, None)["kept_out"] == 0.0


def kept(reason: str) -> dict:
    found = answer("Not in the reports.", matched=False)
    return {**found, "not_in_reports": True, "kept_out": reason, "figures": []}


@pytest.mark.parametrize(
    ("given", "kept_out"),
    [
        (kept("gate"), 1.0),
        (kept("unrelated"), 1.0),
        ({**answer("Not in the reports."), "not_in_reports": True, "matched": False}, 1.0),
        (answer("The closest figures do not show it.", matched=False), 0.0),
        (GOOD, 0.0),
    ],
)
def test_a_negative_is_kept_out_only_when_the_answer_says_it_is_not_in_the_reports(
    given: dict, kept_out: float
) -> None:
    scores = score_answer(NEGATIVE, given)

    assert (scores["case_score"], scores["correct"], scores["kept_out"]) == (kept_out,) * 3


def test_the_summary_puts_correct_over_every_case_first() -> None:
    wrong = answer("Overstress.", cite("18-061 fig06", "18-061", 14, "18-061/fig06"))
    cases = [
        ("positive", score_answer(PHOTO, GOOD)),
        ("positive", score_answer(PHOTO, wrong)),
        ("negative_drawing", score_answer(NEGATIVE, kept("unrelated"))),
        ("negative_unrelated", score_answer(NEGATIVE, GOOD)),
    ]

    summary = summarise_answers(cases)

    assert list(summary) == [
        "correct",
        "report_cited",
        "mode_named",
        "citations_valid",
        "kept_out",
    ]
    assert summary["correct"] == pytest.approx(2 / 4)
    assert (summary["report_cited"], summary["mode_named"]) == (1.0, 0.5)
    assert summary["citations_valid"] == pytest.approx(4 / 5)
    assert summary["kept_out"] == 0.5


def test_a_summary_with_no_citation_does_not_measure_them() -> None:
    summary = summarise_answers([("negative_drawing", score_answer(NEGATIVE, None))])

    assert (summary["citations_valid"], summary["report_cited"]) == (None, None)
