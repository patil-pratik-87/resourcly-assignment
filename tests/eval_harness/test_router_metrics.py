import pytest

from resourcly.eval_harness.metrics import summarise_routes


def routed(expected: str, got: str | None) -> tuple[str, dict]:
    """A case's stratum, the route it should get, and its stored scores."""
    return expected, {"case_score": float(got == expected), "correct": float(got == expected)}


CASES = [
    routed("text", "text"),
    routed("drawing", "drawing"),
    routed("drawing", "drawing"),
    routed("drawing", "photo"),
    routed("photo", "photo"),
    routed("photo", None),
    routed("other", "other"),
    routed("other", "drawing"),
]


def test_accuracy_counts_the_labelled_requests_and_leaves_the_other_files_apart() -> None:
    summary = summarise_routes(CASES)

    assert summary == {
        "accuracy": pytest.approx(4 / 6),
        "drawing_recall": pytest.approx(2 / 3),
        "other_kept_out": 0.5,
    }


def test_a_metric_with_nothing_to_measure_is_empty() -> None:
    summary = summarise_routes([routed("text", "text")])

    assert summary == {"accuracy": 1.0, "drawing_recall": None, "other_kept_out": None}
