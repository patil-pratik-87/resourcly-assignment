import pytest

from resourcly.evals.metrics import score_failure, summarise_failures

FATIGUE = {
    "kind": "positive",
    "expected_report": "18-061",
    "section": "spar_fatigue_N106ER",
    "failure_mode": "fatigue",
}
DRAWING = {"kind": "negative_drawing", "expected_report": "none"}


def figure(name: str, section: str, mode: str) -> dict:
    return {"figure": name, "report": name.split("/")[0], "section": section, "failure_mode": mode}


SAME_SECTION = figure("18-061/fig07", "spar_fatigue_N106ER", "fatigue")
OTHER_SPAR = figure("18-061/fig19", "spar_fatigue_N104ER", "fatigue")
MICRO = figure("18-061/fig14", "microstructure", "reference_no_defect")
HEAT = figure("16-006/fig01", "heat_damage", "heat_damage")
JAM = figure("16-006/fig12", "mixture_control_jam", "jam_corrosion")


def test_a_photo_scores_on_the_top_figure_and_the_modes_of_the_top_three() -> None:
    assert score_failure(FATIGUE, [SAME_SECTION, HEAT]) == {
        "report@1": 1.0,
        "section@1": 1.0,
        "mode@3": 1.0,
    }
    # the right report but another spar: the section is wrong, the mode right
    assert score_failure(FATIGUE, [OTHER_SPAR]) == {
        "report@1": 1.0,
        "section@1": 0.0,
        "mode@3": 1.0,
    }
    assert score_failure(FATIGUE, [HEAT, JAM, MICRO, SAME_SECTION]) == {
        "report@1": 0.0,
        "section@1": 0.0,
        "mode@3": 0.0,
    }
    assert score_failure(FATIGUE, [HEAT, JAM, OTHER_SPAR])["mode@3"] == 1.0


def test_no_figure_or_a_failed_call_misses_a_photo() -> None:
    assert set(score_failure(FATIGUE, []).values()) == {0.0}
    assert set(score_failure(FATIGUE, None).values()) == {0.0}
    assert set(score_failure(FATIGUE, ["not a figure", {"report": None}]).values()) == {0.0}


def test_a_negative_is_kept_out_only_when_no_figure_comes_back() -> None:
    assert score_failure(DRAWING, []) == {"kept_out": 1.0}
    assert score_failure(DRAWING, [HEAT]) == {"kept_out": 0.0}
    # a crash is not a decision to keep the photo out
    assert score_failure(DRAWING, None) == {"kept_out": 0.0}


def test_the_summary_averages_photos_and_negatives_apart() -> None:
    summary = summarise_failures(
        [
            ("positive", score_failure(FATIGUE, [SAME_SECTION])),
            ("positive", score_failure(FATIGUE, [OTHER_SPAR])),
            ("negative_drawing", score_failure(DRAWING, [])),
            ("negative_unrelated", score_failure(DRAWING, [HEAT])),
            ("negative_unrelated", score_failure(DRAWING, [])),
        ]
    )

    assert summary == {
        "cases": 5,
        "photos": 2,
        "negatives": 3,
        "report@1": 1.0,
        "section@1": 0.5,
        "mode@3": 1.0,
        "kept_out": pytest.approx(2 / 3),
    }


def test_a_metric_with_nothing_to_measure_is_empty() -> None:
    summary = summarise_failures([("negative_drawing", score_failure(DRAWING, []))])

    assert summary["section@1"] is None
    assert summary["kept_out"] == 1.0
