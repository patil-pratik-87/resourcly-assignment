from resourcly.adapters.report_passages import Bm25, ReportPassagesAdapter, tokens
from resourcly.bootstrap import PROJECT_ROOT
from resourcly.models import Passage

REPORTS = PROJECT_ROOT / "data" / "reports"


def test_words_are_lower_case_without_stop_words() -> None:
    assert tokens("Where did the Fatigue cracks start, at LC-1?") == [
        "fatigue",
        "cracks",
        "start",
        "lc",
        "1",
    ]


def test_bm25_ranks_the_passage_with_the_rarer_word_first() -> None:
    passages = [
        Passage(report="a", page=1, text="the spar cap had fatigue cracks"),
        Passage(report="a", page=2, text="the spar was painted"),
        Passage(report="a", page=3, text="nothing here"),
    ]

    ranked = Bm25(passages).search("fatigue in the spar", 3)

    assert [p.page for p in ranked] == [1, 2]


def test_the_reports_answer_a_question_with_the_page_that_says_it() -> None:
    search = ReportPassagesAdapter(REPORTS)

    [best, *_] = search.search("What throttle position was measured on the accident control?", 6)
    found = {p.source for p in search.search("Where was corrosion found in the mixture?", 3)}

    assert best.source == "16-006 p2"
    assert "16-006 p4" in found


def test_figure_captions_are_passages_labelled_with_their_section() -> None:
    search = ReportPassagesAdapter(REPORTS)

    found = search.search("Figure 2 throttle arm fractured threaded section", 3)

    caption = next(p for p in found if p.text.startswith("Figure 2"))
    assert caption.source == "24-013 p4"
    assert "bending overstress" in caption.text


def test_a_query_with_no_known_word_finds_nothing() -> None:
    assert ReportPassagesAdapter(REPORTS).search("zzzz qqqq", 6) == []
