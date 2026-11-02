"""The report figure images a photo answer cites, and the answer's shape on a request item."""

from collections.abc import Iterator

import pymupdf
import pytest
from fastapi.testclient import TestClient

from resourcly.api import create_app
from resourcly.bootstrap import Settings
from resourcly.models import PhotoAnswer, RequestItem


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as client:
        yield client


def test_a_cited_figure_is_served_as_a_png_no_larger_than_asked(client: TestClient) -> None:
    response = client.get("/api/reports/18-061/figures/5.png", params={"max_side": 300})

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    image = pymupdf.Pixmap(response.content)
    assert max(image.width, image.height) == 300


@pytest.mark.parametrize("path", ["18-061/figures/99.png", "99-999/figures/1.png"])
def test_a_figure_the_reports_do_not_have_is_not_found(client: TestClient, path: str) -> None:
    response = client.get(f"/api/reports/{path}")

    assert response.status_code == 404
    assert "no figure" in response.json()["detail"]


def test_the_agent_names_the_failure_finder_and_answer_versions(client: TestClient) -> None:
    agent = client.get("/api/agent").json()

    assert agent["failure"] == "shuffled-v0 (shuffled)"
    assert agent["answer"] == "captions-v0 (captions)"


def test_a_photo_item_carries_its_answer_with_cited_figures_and_marked_actions() -> None:
    item = RequestItem.model_validate(
        {
            "item_id": "crack",
            "kind": "file",
            "name": "crack.jpg",
            "status": "answered",
            "reply": "Fatigue cracking in the lower spar cap.",
            "answer": {
                "not_in_reports": False,
                "matched": True,
                "answer": "Fatigue cracking in the lower spar cap.",
                "findings": [
                    {
                        "statement": "Fatigue origins were at the lower surface.",
                        "citation": {
                            "source": "18-061 fig05",
                            "report": "18-061",
                            "page": 13,
                            "figure": "18-061/fig05",
                        },
                    }
                ],
                "actions": [
                    {
                        "action": "Inspect the spar cap for cracks at the holes.",
                        "basis": "inferred",
                        "citation": None,
                    },
                    {
                        "action": "Measure the bolt torque.",
                        "basis": "stated",
                        "citation": {"source": "18-061 p4", "report": "18-061", "page": 4},
                    },
                ],
                "figures": [
                    {
                        "figure": "18-061/fig05",
                        "report": "18-061",
                        "section": "spar_fatigue_N106ER",
                        "failure_mode": "fatigue",
                        "score": 0.83,
                    }
                ],
            },
        }
    )

    answer = item.answer
    assert isinstance(answer, PhotoAnswer)
    assert answer.findings[0].citation.figure == "18-061/fig05"
    assert answer.actions[1].citation.figure is None
    assert [action.basis for action in answer.actions] == ["inferred", "stated"]
    assert answer.figures[0].score == 0.83


def test_a_photo_the_reports_do_not_show_has_no_figures() -> None:
    answer = PhotoAnswer(
        not_in_reports=True, matched=False, answer="Not in the reports.", findings=[], actions=[]
    )

    assert answer.figures == []
    assert RequestItem(item_id="a", kind="file", name="a.png").answer is None


def test_answering_is_a_status_of_work_in_progress() -> None:
    item = RequestItem(item_id="a", kind="file", name="a.png", status="answering")

    assert item.status == "answering"
