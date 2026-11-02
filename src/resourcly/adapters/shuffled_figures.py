import random
import tomllib
from collections.abc import Collection
from pathlib import Path

from resourcly.models import Attachment, FigureMatch


class ShuffledFiguresAdapter:
    """A model-free failure finder: every report figure in one random order, whatever the photo.

    The order is shuffled once with `seed`, so a run gives the same answer every time. It never
    says a photo matches no report. It sets the floor a real finder must beat.
    """

    def __init__(self, sections: Path, seed: int = 0):
        figures = report_figures(sections)
        random.Random(seed).shuffle(figures)
        self.figures = figures

    def find(self, photo: Attachment, exclude: Collection[str] = ()) -> list[FigureMatch]:
        return [figure for figure in self.figures if figure.figure not in exclude]


def report_figures(sections: Path) -> list[FigureMatch]:
    """Every report figure with its section and failure mode, from the figure ranges of
    data/reports/sections.toml, in report and figure order."""
    table = tomllib.loads(sections.read_text(encoding="utf-8"))
    figures = []
    for entry in table["section"]:
        first, last = entry["figures"]
        figures += [
            FigureMatch(
                figure=f"{entry['report']}/fig{number:02d}",
                report=entry["report"],
                section=entry["section"],
                failure_mode=entry["failure_mode"],
            )
            for number in range(first, last + 1)
        ]
    return sorted(figures, key=lambda figure: figure.figure)
