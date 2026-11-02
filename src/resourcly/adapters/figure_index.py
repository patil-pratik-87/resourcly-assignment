"""The figure index: every report figure with what the report says about it and its image vector.

scripts/build_figure_index.py writes one next to each failure finder version. It records the
encoder, the vector recipe and the input size its vectors were made with, so a finder whose
encoder differs refuses to load it. The figure images are not kept: each figure's page and box
render it again from its report.
"""

import re
import tomllib
from io import BytesIO
from pathlib import Path

from PIL import Image
from pydantic import BaseModel, ValidationError

from resourcly.adapters.report_figures import cut_report, render_figure
from resourcly.errors import InvalidVersion, NotFound
from resourcly.models import Attachment, FigureEvidence, ReportEvidence
from resourcly.ports import ImageEncoderPort

DIGITS = 6  # decimals kept of each vector number; enough for cosine similarity
NUMBERS = re.compile(r"\[\s*(-?[\d.e+-]+(?:,\s*-?[\d.e+-]+)*)\s*\]")


class IndexedFigure(FigureEvidence):
    bbox: tuple[float, float, float, float]  # the figure on its page, in PDF points
    vector: list[float]  # length 1


class FigureIndex(BaseModel):
    encoder_model: str
    recipe: str
    input_size: int
    render_dpi: int  # the figures were rendered at this resolution to make their vectors
    revision: str  # the snapshot of the encoder's weights that made the vectors
    reports: list[ReportEvidence]
    figures: list[IndexedFigure]

    @classmethod
    def load(cls, path: Path) -> "FigureIndex":
        try:
            index = cls.model_validate_json(path.read_bytes())
        except (OSError, ValidationError) as error:
            raise InvalidVersion(
                f"{path.name} cannot be read as a figure index: {error}"
            ) from error
        lengths = {len(figure.vector) for figure in index.figures}
        if len(lengths) > 1:
            raise InvalidVersion(f"{path.name} holds vectors of {len(lengths)} lengths")
        reports = {report.report for report in index.reports}
        for figure in index.figures:
            if figure.report not in reports:
                raise InvalidVersion(
                    f"{path.name}: {figure.figure} is from {figure.report},"
                    " which the index does not list"
                )
        return index

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        text = self.model_dump_json(indent=1)
        # a list of numbers, such as a vector, on one line
        text = NUMBERS.sub(lambda found: "[" + re.sub(r"\s+", "", found.group(1)) + "]", text)
        path.write_text(text + "\n", encoding="utf-8")

    def check(self, encoder: ImageEncoderPort) -> None:
        """Refuse an encoder whose vectors cannot be compared with the index's."""
        made = (self.encoder_model, self.recipe, self.input_size)
        given = (encoder.model_id, encoder.recipe, encoder.input_size)
        if made != given:
            raise InvalidVersion(
                f"the figure index was made with {made[0]}, recipe {made[1]}, input size"
                f" {made[2]}; the finder's encoder is {given[0]}, recipe {given[1]}, input size"
                f" {given[2]}"
            )


def build_index(
    reports_dir: Path, sections: Path, encoder: ImageEncoderPort, dpi: int
) -> FigureIndex:
    """Cut every report PDF in the folder into figures, label each one and embed its image.

    Each figure's section and failure mode come from sections.toml. A figure without a label,
    or a label without a figure, raises ValueError.
    """
    labels = _labels(sections)
    reports, figures = [], []
    for pdf in sorted(reports_dir.glob("*.pdf")):
        cut = cut_report(pdf)
        reports.append(
            ReportEvidence(
                report=cut.report,
                file=pdf.name,
                vehicle=cut.vehicle,
                components=cut.components,
                closing=cut.closing,
            )
        )
        for figure in cut.figures:
            if figure.figure not in labels:
                raise ValueError(f"{figure.figure} has no section in {sections.name}")
            section, failure_mode = labels.pop(figure.figure)
            image = render_figure(pdf, figure.page, figure.bbox, dpi)
            vector = encoder.encode(Attachment(f"{figure.figure}.png", "image/png", image))
            figures.append(
                IndexedFigure(
                    figure=figure.figure,
                    report=figure.report,
                    page=figure.page,
                    section=section,
                    failure_mode=failure_mode,
                    caption=figure.caption,
                    citing=figure.citing,
                    bbox=tuple(round(value, 2) for value in figure.bbox),
                    vector=[round(value, DIGITS) for value in vector],
                )
            )
    if labels:
        raise ValueError(f"{', '.join(sorted(labels))} labelled in {sections.name} but not found")
    return FigureIndex(
        encoder_model=encoder.model_id,
        recipe=encoder.recipe,
        input_size=encoder.input_size,
        render_dpi=dpi,
        revision=encoder.revision,
        reports=reports,
        figures=figures,
    )


class IndexedEvidenceAdapter:
    """The reports' text from a figure index, and each figure's image rendered from its PDF."""

    def __init__(self, index: FigureIndex, reports_dir: Path):
        self.reports_dir = reports_dir
        self.render_dpi = index.render_dpi
        self._figures = {figure.figure: figure for figure in index.figures}
        self._reports = {report.report: report for report in index.reports}

    def figure(self, figure: str) -> FigureEvidence:
        return FigureEvidence.model_validate(self._indexed(figure).model_dump())

    def figure_image(self, figure: str, max_side: int) -> bytes:
        found = self._indexed(figure)
        pdf = self.reports_dir / self._reports[found.report].file
        rendered = Image.open(BytesIO(render_figure(pdf, found.page, found.bbox, self.render_dpi)))
        rendered.thumbnail((max_side, max_side), Image.Resampling.BICUBIC)
        buffer = BytesIO()
        rendered.save(buffer, "PNG")
        return buffer.getvalue()

    def report(self, report: str) -> ReportEvidence:
        if report not in self._reports:
            raise NotFound(f"no report {report} in the figure index")
        return self._reports[report]

    def _indexed(self, figure: str) -> IndexedFigure:
        if figure not in self._figures:
            raise NotFound(f"no figure {figure} in the figure index")
        return self._figures[figure]


def _labels(sections: Path) -> dict[str, tuple[str, str]]:
    """The section and failure mode of each figure, by figure id, from sections.toml."""
    table = tomllib.loads(sections.read_text(encoding="utf-8"))
    labels = {}
    for entry in table["section"]:
        first, last = entry["figures"]
        for number in range(first, last + 1):
            labels[f"{entry['report']}/fig{number:02d}"] = (
                entry["section"],
                entry["failure_mode"],
            )
    return labels
