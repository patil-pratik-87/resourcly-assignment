import pytest

from resourcly.evals.metrics import RouteOutcome, summarise_routes


def outcome(case_id, expected, route, layer="probe", ms=30.0, attached=True) -> RouteOutcome:
    return RouteOutcome(case_id, expected, route, layer, f"why {case_id}", ms, attached)


OUTCOMES = [
    outcome("t1", "text", "text", "structure", 0.1, attached=False),
    outcome("d1", "drawing", "drawing", "structure", 20.0),
    outcome("d2", "drawing", "drawing", "probe", 30.0),
    outcome("d3", "drawing", "photo", "vlm", 3000.0),
    outcome("p1", "photo", "photo", "probe", 40.0),
    outcome("p2", "photo", None, None, None),
    outcome("o1", "other", "other", "structure", 10.0),
    outcome("o2", "other", "drawing", "probe", 30.0),
]


def test_accuracy_counts_the_labelled_requests_and_leaves_the_other_files_apart() -> None:
    summary = summarise_routes(OUTCOMES)

    assert summary["cases"] == 8
    assert summary["accuracy"] == pytest.approx(4 / 6)
    assert summary["other_cases"] == 2
    assert summary["other_kept_out"] == pytest.approx(0.5)


def test_recall_per_route_and_no_other_route_metric() -> None:
    summary = summarise_routes(OUTCOMES)

    assert summary["drawing_recall"] == pytest.approx(2 / 3)
    assert summary["photo_recall"] == pytest.approx(1 / 2)
    assert summary["text_recall"] == pytest.approx(1.0)
    numbers = {k for k, v in summary.items() if not isinstance(v, list | dict)}
    assert numbers == {
        "cases",
        "accuracy",
        "drawing_recall",
        "photo_recall",
        "text_recall",
        "other_cases",
        "other_kept_out",
        "escalation_rate",
        "median_ms",
    }


def test_escalation_and_time_cover_the_labelled_files() -> None:
    summary = summarise_routes(OUTCOMES)

    # d1, d2, d3, p1 and p2: one of them by the vlm
    assert summary["escalation_rate"] == pytest.approx(1 / 5)
    assert summary["median_ms"] == pytest.approx(35.0)  # not swayed by a model's first load


def test_mistakes_and_misrouted_other_files_are_listed_with_the_layer_and_reason() -> None:
    summary = summarise_routes(OUTCOMES)

    assert summary["mistakes"] == [
        {"case": "d3", "expected": "drawing", "got": "photo", "layer": "vlm", "reason": "why d3"},
        {"case": "p2", "expected": "photo", "got": "(error)", "layer": "-", "reason": "why p2"},
    ]
    # an other file sent to a real case would reach that case's reader, so it is listed apart
    assert summary["other_misrouted"] == [
        {
            "case": "o2",
            "expected": "other",
            "got": "drawing",
            "layer": "probe",
            "reason": "why o2",
        }
    ]
    assert summary["confusion"] == {
        "drawing": {"drawing": 2, "photo": 1},
        "photo": {"(error)": 1, "photo": 1},
        "text": {"text": 1},
        "other": {"drawing": 1, "other": 1},
    }


def test_a_metric_with_nothing_to_measure_is_empty() -> None:
    summary = summarise_routes([outcome("t1", "text", "text", "structure", attached=False)])

    assert summary["drawing_recall"] is None
    assert summary["other_kept_out"] is None
    assert summary["escalation_rate"] is None
    assert summary["median_ms"] is None
