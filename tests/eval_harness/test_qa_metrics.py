import pytest

from resourcly.eval_harness.metrics import score_question, summarise_questions

FLATNESS = {"kind": "drawing", "expected": [{"value": 0.2, "unit": "mm"}]}
REVISION = {"kind": "drawing", "expected": [{"raw": "Rev D"}]}


def shown(outcome: str, *records: dict, **extra) -> dict:
    return {"outcome": outcome, "shown_values": list(records), **extra}


@pytest.mark.parametrize(
    ("gold", "prediction", "score"),
    [
        (FLATNESS, shown("answer", {"raw": "▱ 0.2", "value": 0.2, "unit": "mm"}), 1.0),
        (FLATNESS, shown("answer", {"raw": "▱ 1.5", "value": 1.5, "unit": "mm"}), -1.0),
        (FLATNESS, shown("answer", {"raw": "0.2", "value": 0.2, "unit": "in"}), -1.0),
        (
            FLATNESS,
            shown("candidates", {"value": 1.5, "unit": "mm"}, {"value": 0.2, "unit": "mm"}),
            0.5,
        ),
        (FLATNESS, shown("candidates", {"value": 1.5, "unit": "mm"}), 0.0),
        (FLATNESS, shown("none"), 0.0),
        (FLATNESS, None, 0.0),
        (REVISION, shown("answer", {"raw": "Rev  D", "value": None, "unit": None}), 1.0),
        ({"kind": "none", "route": "drawing"}, shown("none", {"value": 1}), 1.0),
        ({"kind": "none", "route": "drawing"}, shown("candidates"), 0.0),
        ({"kind": "none", "route": "drawing"}, shown("answer", {"value": 1}), -1.0),
    ],
)
def test_a_drawing_answer_scores_by_the_value_it_shows(gold, prediction, score) -> None:
    assert score_question(gold, prediction)["case_score"] == score


PAGES = {"kind": "text", "pages": ["16-006 p4"]}


def cited(*refs: str, outcome: str = "answer") -> dict:
    return {"outcome": outcome, "citations": [{"ref": ref} for ref in refs], "cites": list(refs)}


@pytest.mark.parametrize(
    ("gold", "prediction", "score"),
    [
        (PAGES, cited("16-006 p2", "16-006 p4"), 1.0),
        (PAGES, cited("16-006 p2"), -1.0),
        (PAGES, cited(outcome="none"), 0.0),
        ({"kind": "none", "route": "text"}, cited(outcome="none"), 1.0),
        ({"kind": "none", "route": "text"}, cited("16-006 p2"), -1.0),
    ],
)
def test_a_text_answer_scores_by_the_pages_it_cites(gold, prediction, score) -> None:
    assert score_question(gold, prediction)["case_score"] == score


SPAR = {
    "kind": "photo",
    "expected_report": "18-061",
    "section": "spar_fatigue_N106ER",
    "failure_mode": "fatigue",
}
FIG05 = {"figure": "18-061/fig05", "report": "18-061", "section": "spar_fatigue_N106ER"}
FIG13 = {"figure": "18-061/fig13", "report": "18-061", "section": "microstructure"}


def photo(matched: bool, figures: list[dict], *cites: str) -> dict:
    findings = [
        {"citation": {"source": c.replace("/", " "), "report": c[:6], "page": 1, "figure": c}}
        for c in cites
    ]
    return {"matched": matched, "not_in_reports": False, "figures": figures, "findings": findings}


@pytest.mark.parametrize(
    ("gold", "prediction", "score"),
    [
        (SPAR, photo(True, [FIG13, FIG05], "18-061/fig05"), 1.0),
        (SPAR, photo(True, [FIG13, FIG05], "18-061/fig13"), -1.0),
        (SPAR, photo(True, [FIG13, FIG05], "18-061/fig13", "18-061/fig05"), -1.0),
        (SPAR, photo(True, [FIG05, FIG13]), 1.0),
        (SPAR, photo(False, [FIG05]), 0.0),
        ({"kind": "none", "route": "photo"}, photo(False, [FIG05]), 1.0),
        ({"kind": "none", "route": "photo"}, photo(True, [FIG05], "18-061/fig05"), -1.0),
        ({"kind": "none", "route": "photo"}, None, 0.0),
    ],
)
def test_a_photo_answer_scores_by_the_figures_it_cites(gold, prediction, score) -> None:
    assert score_question(gold, prediction)["case_score"] == score


def test_the_summary_leads_with_the_mean_and_counts_wrong_answers_and_bad_citations() -> None:
    cases = [
        ("drawing", {"case_score": 1.0, "wrong": 0.0, "valid_cites": 1, "dropped_cites": 1}),
        ("place", {"case_score": -1.0, "wrong": 1.0, "valid_cites": 2, "dropped_cites": 0}),
        ("text", {"case_score": 0.5, "wrong": 0.0, "valid_cites": 0, "dropped_cites": 0}),
    ]

    summary = summarise_questions(cases)

    assert list(summary)[:3] == ["answer_score", "wrong_shown", "citations_valid"]
    assert summary["answer_score"] == pytest.approx(0.5 / 3)
    assert summary["wrong_shown"] == pytest.approx(1 / 3)
    assert summary["citations_valid"] == 0.75
    assert (summary["drawing"], summary["place"], summary["photo"]) == (1.0, -1.0, None)
