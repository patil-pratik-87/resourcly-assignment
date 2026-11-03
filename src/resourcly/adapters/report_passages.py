"""Searches the NTSB reports' paragraphs and figure captions with BM25, for a text answer to cite.

Each report is cut as the figure index cuts it (`report_figures.cut_report`): its paragraphs, each
cited by the page it starts on, and its figure captions, each on its figure's page and labelled
with the section `sections.toml` gives the figure. The failure mode is left out: a label such as
"jam corrosion" would match every caption of its section to a question about corrosion. The words
are lower case, without stop words; no model is run.
"""

import math
import re
from collections import Counter
from pathlib import Path

from resourcly.adapters.figure_index import figure_labels
from resourcly.adapters.report_figures import cut_report
from resourcly.models import Passage

STOP_WORDS = frozenset(
    "a an and are as at be by can could did do does for from had has have how i in is it its"
    " me of on or so that the their there this to was were what when where which who why will"
    " with".split()
)


def tokens(text: str) -> list[str]:
    return [word for word in re.findall(r"[a-z0-9]+", text.lower()) if word not in STOP_WORDS]


class Bm25:
    """Okapi BM25 over a fixed list of passages."""

    def __init__(self, passages: list[Passage], k1: float = 1.5, b: float = 0.75):
        self.passages = passages
        self.k1 = k1
        self.b = b
        self.counts = [Counter(tokens(passage.text)) for passage in passages]
        self.lengths = [sum(counts.values()) for counts in self.counts]
        self.average = sum(self.lengths) / len(self.lengths) if self.lengths else 0.0
        frequency = Counter(word for counts in self.counts for word in counts)
        n = len(passages)
        self.idf = {
            word: math.log(1 + (n - found + 0.5) / (found + 0.5))
            for word, found in frequency.items()
        }

    def search(self, query: str, k: int) -> list[Passage]:
        words = [word for word in dict.fromkeys(tokens(query)) if word in self.idf]
        scored = []
        for index, counts in enumerate(self.counts):
            score = 0.0
            norm = self.k1 * (1 - self.b + self.b * self.lengths[index] / self.average)
            for word in words:
                found = counts.get(word, 0)
                if found:
                    score += self.idf[word] * found * (self.k1 + 1) / (found + norm)
            if score > 0:
                scored.append((score, index))
        scored.sort(key=lambda pair: (-pair[0], pair[1]))
        return [self.passages[index] for _, index in scored[:k]]


class ReportPassagesAdapter:
    """The paragraphs and captions of every report in `reports`, searched with BM25."""

    def __init__(self, reports: Path):
        labels = figure_labels(reports / "sections.toml")
        passages: list[Passage] = []
        for pdf in sorted(reports.glob("*.pdf")):
            cut = cut_report(pdf)
            passages += cut.paragraphs
            for figure in cut.figures:
                section = labels.get(figure.figure, ("unlabelled", ""))[0].replace("_", " ")
                text = f"{figure.caption} ({section})"
                passages.append(Passage(report=figure.report, page=figure.page, text=text))
        self.index = Bm25(passages)

    def search(self, query: str, k: int) -> list[Passage]:
        return self.index.search(query, k)
