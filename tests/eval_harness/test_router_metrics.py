import pytest

from resourcly.eval_harness.metrics import RouteOutcome, summarise_routes


def outcome(case_id, expected, route, layer="probe") -> RouteOutcome:
    return RouteOutcome(case_id, expected, route, layer, f"why {case_id}")


OUTCOMES = [
    outcome("t1", "text", "text", "structure"),
    outcome("d1", "drawing", "drawing", "structure"),
    outcome("d2", "drawing", "drawing"),
    outcome("d3", "drawing", "photo", "vlm"),
    outcome("p1", "photo", "photo"),
    outcome("p2", "photo", None, None),
    outcome("o1", "other", "other", "structure"),
    outcome("o2", "other", "drawing"),
]


def test_accuracy_counts_the_labelled_requests_and_leaves_the_other_files_apart() -> None:
    summary = summarise_routes(OUTCOMES)

    assert summary["accuracy"] == pytest.approx(4 / 6)
    assert summary["drawing_recall"] == pytest.approx(2 / 3)
    assert summary["other_kept_out"] == pytest.approx(0.5)
    assert set(summary) == {"accuracy", "drawing_recall", "other_kept_out", "mistakes"}


def test_every_wrong_route_is_listed_with_the_layer_and_reason() -> None:
    summary = summarise_routes(OUTCOMES)

    assert summary["mistakes"] == [
        {"case": "d3", "expected": "drawing", "got": "photo", "layer": "vlm", "reason": "why d3"},
        # an other file sent to a real case would reach that case's reader
        {"case": "o2", "expected": "other", "got": "drawing", "layer": "probe", "reason": "why o2"},
        {"case": "p2", "expected": "photo", "got": "(error)", "layer": "-", "reason": "why p2"},
    ]


def test_a_metric_with_nothing_to_measure_is_empty() -> None:
    summary = summarise_routes([outcome("t1", "text", "text", "structure")])

    assert summary["accuracy"] == 1.0
    assert summary["drawing_recall"] is None
    assert summary["other_kept_out"] is None
