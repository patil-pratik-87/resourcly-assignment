import json
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from resourcly.adapters.figure_index import FigureIndex, IndexedEvidenceAdapter, build_index
from resourcly.adapters.nearest_figures import NearestFiguresAdapter
from resourcly.bootstrap import PROJECT_ROOT
from resourcly.errors import InvalidVersion, NotFound
from resourcly.models import Attachment
from tests.conftest import png

REPORTS = PROJECT_ROOT / "data" / "reports"
PHOTO = Attachment("crack.png", "image/png", png())


class FakeEncoder:
    """Stands in for DINOv2: every picture becomes the same vector."""

    def __init__(self, vector=(1.0, 0.0), model_id="org/dino", recipe="cls_patch_mean", size=224):
        self.vector = list(vector)
        self.model_id = model_id
        self.recipe = recipe
        self.input_size = size
        self.revision = "ed25f3a"
        self.seen: list[Attachment] = []

    def encode(self, attachment: Attachment) -> list[float]:
        self.seen.append(attachment)
        return self.vector


def figure(name: str, vector: list[float], mode: str = "fatigue") -> dict:
    report = name.split("/")[0]
    return {
        "figure": name,
        "report": report,
        "page": 13,
        "bbox": [10.0, 20.0, 110.0, 220.0],
        "section": "spar_fatigue_N106ER",
        "failure_mode": mode,
        "caption": f"Figure {int(name[-2:])}. A view.",
        "citing": [{"report": report, "page": 2, "text": f"As shown in figure {int(name[-2:])}."}],
        "vector": vector,
    }


def index(*figures: dict, **settings) -> FigureIndex:
    return FigureIndex.model_validate(
        {
            "encoder_model": "org/dino",
            "recipe": "cls_patch_mean",
            "input_size": 224,
            "render_dpi": 150,
            "revision": "ed25f3a",
            "reports": [
                {
                    "report": "18-061",
                    "file": "ntsb_18-061.pdf",
                    "vehicle": "Piper PA-28R-201, N106ER",
                    "components": "Center wing box assembly",
                    "closing": [{"report": "18-061", "page": 9, "text": "The last paragraph."}],
                }
            ],
            "figures": list(figures),
            **settings,
        }
    )


SPARS = index(
    figure("18-061/fig05", [0.6, 0.8]),
    figure("18-061/fig06", [1.0, 0.0]),
    figure("18-061/fig13", [0.0, 1.0], mode="reference_no_defect"),
)


def test_the_finder_ranks_the_figures_by_cosine_similarity_best_first() -> None:
    finder = NearestFiguresAdapter(FakeEncoder([1.0, 0.0]), SPARS, threshold=0.28, top=2)

    found = finder.find(PHOTO)

    assert [(match.figure, match.score) for match in found] == [
        ("18-061/fig06", 1.0),
        ("18-061/fig05", 0.6),
    ]
    assert (found[0].report, found[0].section, found[0].failure_mode) == (
        "18-061",
        "spar_fatigue_N106ER",
        "fatigue",
    )


def test_a_photo_far_from_every_figure_matches_no_report() -> None:
    finder = NearestFiguresAdapter(FakeEncoder([-1.0, 0.0]), SPARS, threshold=0.28, top=3)

    assert finder.find(PHOTO) == []


def test_the_best_figure_at_the_threshold_passes_the_gate() -> None:
    finder = NearestFiguresAdapter(FakeEncoder([0.0, 1.0]), SPARS, threshold=1.0, top=1)

    assert [match.figure for match in finder.find(PHOTO)] == ["18-061/fig13"]


@pytest.mark.parametrize(
    ("encoder", "differs"),
    [
        (FakeEncoder(model_id="org/other"), "org/other"),
        (FakeEncoder(recipe="cls"), "recipe cls"),
        (FakeEncoder(size=448), "input size 448"),
    ],
)
def test_an_index_made_with_another_encoder_is_refused(encoder: FakeEncoder, differs: str) -> None:
    with pytest.raises(InvalidVersion, match=differs):
        NearestFiguresAdapter(encoder, SPARS, threshold=0.28, top=3)


def test_a_vector_of_another_length_is_refused() -> None:
    finder = NearestFiguresAdapter(FakeEncoder([1.0, 0.0, 0.0]), SPARS, threshold=0.28, top=3)

    with pytest.raises(ValueError, match="3 numbers, the index holds 2"):
        finder.find(PHOTO)


def test_the_index_loads_what_it_saved(tmp_path: Path) -> None:
    path = tmp_path / "index.json"
    SPARS.save(path)

    assert FigureIndex.load(path) == SPARS


@pytest.mark.parametrize(
    ("content", "problem"),
    [
        ("not json", "cannot be read as a figure index"),
        ('{"encoder_model": "org/dino"}', "cannot be read as a figure index"),
    ],
)
def test_a_broken_index_is_refused(tmp_path: Path, content: str, problem: str) -> None:
    path = tmp_path / "index.json"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(InvalidVersion, match=problem):
        FigureIndex.load(path)


def test_an_index_whose_vectors_differ_in_length_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "index.json"
    data = json.loads(SPARS.model_dump_json())
    data["figures"][0]["vector"] = [1.0, 0.0, 0.0]
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(InvalidVersion, match="vectors of 2 lengths"):
        FigureIndex.load(path)


def test_an_index_figure_from_an_unlisted_report_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "index.json"
    data = json.loads(SPARS.model_dump_json())
    data["figures"][0]["report"] = "99-999"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(InvalidVersion, match="99-999"):
        FigureIndex.load(path)


def test_the_index_is_built_from_every_figure_of_the_reports_with_its_label() -> None:
    encoder = FakeEncoder([0.6, 0.8])

    built = build_index(REPORTS, REPORTS / "sections.toml", encoder, dpi=50)

    assert len(built.figures) == len(encoder.seen) == 46
    assert (built.encoder_model, built.recipe, built.input_size) == (
        "org/dino",
        "cls_patch_mean",
        224,
    )
    assert (built.render_dpi, built.revision) == (50, "ed25f3a")
    assert [report.report for report in built.reports] == ["16-006", "18-061", "24-013"]
    fig05 = next(f for f in built.figures if f.figure == "18-061/fig05")
    assert (fig05.section, fig05.failure_mode, fig05.page) == ("spar_fatigue_N106ER", "fatigue", 13)
    assert fig05.vector == [0.6, 0.8]
    assert Image.open(BytesIO(encoder.seen[0].data)).format == "PNG"


def test_a_figure_without_a_label_stops_the_build(tmp_path: Path) -> None:
    sections = tmp_path / "sections.toml"
    sections.write_text(
        '[[section]]\nreport = "24-013"\nfigures = [1, 4]\nsection = "throttle_arm"\n'
        'failure_mode = "overstress"\n',
        encoding="utf-8",
    )
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "ntsb_24-013.pdf").write_bytes((REPORTS / "ntsb_24-013.pdf").read_bytes())

    with pytest.raises(ValueError, match="24-013/fig05 has no section"):
        build_index(reports, sections, FakeEncoder(), dpi=50)


def test_the_evidence_gives_a_figure_its_caption_and_citing_paragraphs() -> None:
    evidence = IndexedEvidenceAdapter(SPARS, REPORTS)

    fig05 = evidence.figure("18-061/fig05")

    assert fig05.caption == "Figure 5. A view."
    assert [passage.source for passage in fig05.citing] == ["18-061 p2"]
    assert evidence.report("18-061").closing[0].source == "18-061 p9"
    with pytest.raises(NotFound):
        evidence.figure("18-061/fig99")


def test_the_evidence_renders_a_figure_from_its_report_no_larger_than_asked() -> None:
    evidence = IndexedEvidenceAdapter(SPARS, REPORTS)

    image = Image.open(BytesIO(evidence.figure_image("18-061/fig05", max_side=120)))

    assert image.format == "PNG"
    assert max(image.size) == 120
