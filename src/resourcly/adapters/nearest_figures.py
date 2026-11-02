from resourcly.adapters.figure_index import FigureIndex
from resourcly.models import Attachment, FigureMatch
from resourcly.ports import ImageEncoderPort


class NearestFiguresAdapter:
    """A failure finder that ranks the report figures by how close their image is to the photo.

    The photo's vector and each figure's vector in the index are compared by cosine similarity,
    brute force, which is quick for a few thousand figures. When even the best figure is below
    `threshold`, no report shows the failure, and the finder returns no figure. Otherwise it
    returns the `top` figures, best first, each with its similarity as the score.
    """

    def __init__(self, encoder: ImageEncoderPort, index: FigureIndex, threshold: float, top: int):
        index.check(encoder)
        self.encoder = encoder
        self.index = index
        self.threshold = threshold
        self.top = top

    def find(self, photo: Attachment) -> list[FigureMatch]:
        vector = self.encoder.encode(photo)
        size = len(self.index.figures[0].vector) if self.index.figures else len(vector)
        if len(vector) != size:
            raise ValueError(
                f"the photo's vector has {len(vector)} numbers, the index holds {size}"
            )
        scored = sorted(
            (
                (sum(a * b for a, b in zip(vector, figure.vector, strict=True)), figure)
                for figure in self.index.figures
            ),
            key=lambda pair: -pair[0],
        )
        if not scored or scored[0][0] < self.threshold:
            return []
        return [
            FigureMatch(
                figure=figure.figure,
                report=figure.report,
                section=figure.section,
                failure_mode=figure.failure_mode,
                score=round(score, 4),
            )
            for score, figure in scored[: self.top]
        ]
