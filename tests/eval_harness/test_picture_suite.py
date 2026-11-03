"""The reader-pictures suite: a picture of a drawing page is read as an image upload is."""

from dataclasses import replace
from pathlib import Path

import pymupdf
import pytest

from resourcly.bootstrap import PROJECT_ROOT, READERS, Implementation, Settings
from resourcly.eval_harness import harness
from resourcly.eval_harness.store import SqliteResultStore
from resourcly.models import ReaderOutput
from tests.conftest import CTC01
from tests.eval_harness.test_route_gold import row, write_routes

ROWS = [
    row("d_ctc01_p1_r72", "drawing", "ctc01", variant="render_72", source="nist"),
    row("d_ctc01_p2_jpeg", "drawing", "ctc01", variant="jpeg", source="nist"),
    row("d_ctc01_pdf", "drawing", "ctc01", kind="pdf", file="items/drawing/ctc01.pdf"),
    row("d_ctc09_p1_photo", "drawing", "ctc09", variant="photo", source="nist"),
    row("p_16006_x32", "photo", "ntsb_16-006"),
]
SPLITS = f'[reader]\ndev = ["{CTC01}"]\n[router]\ndev = ["ctc01"]\n'


class PageReader:
    """Reads the one page it is given as two values, and says what it was given."""

    seen: list[tuple[str, int]] = []

    def __init__(self, folder: Path):
        self.folder = folder

    def read(self, drawing: str, progress=None) -> ReaderOutput:
        with pymupdf.open(self.folder / f"{drawing}.pdf") as pdf:
            self.seen.append((drawing, pdf.page_count))
        value = {"page": 1, "unit": "deg", "kind": "angular", "value": 60, "raw": "60° ±0.5°"}
        return ReaderOutput(document={"drawing": drawing, "page_count": 1, "values": [value]})


@pytest.fixture
def pictures(gold_dir: Path, settings: Settings, tmp_path: Path, monkeypatch) -> Settings:
    write_routes(gold_dir, ROWS, SPLITS)
    with pymupdf.open(PROJECT_ROOT / "data" / "drawings" / f"{CTC01}.pdf") as pdf:
        picture = pdf[0].get_pixmap(dpi=72).tobytes("png")
    for r in ROWS:
        path = gold_dir / "routes" / r["file"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(picture)
    PageReader.seen = []
    monkeypatch.setitem(READERS, "page", Implementation(lambda s, p: PageReader(s.drawings_dir)))
    versions = tmp_path / "versions" / "reader"
    versions.mkdir(parents=True)
    (versions / "page-v1.toml").write_text('impl = "page"\n', encoding="utf-8")
    return replace(settings, versions_dir=versions.parent)


def test_each_picture_of_a_gold_drawing_page_is_read_as_an_upload_and_scored_on_its_page(
    pictures: Settings, store: SqliteResultStore
) -> None:
    run = harness.run("reader-pictures", "page-v1", settings=pictures, store=store)
    cases = {case.case_id: case for case in store.cases(run.run_id)}

    # the PDF is not a picture, ctc09 has no gold, and the photo is not a drawing
    assert sorted(cases) == ["d_ctc01_p1_r72", "d_ctc01_p2_jpeg"]
    # each picture becomes a one-page PDF, as an image upload does
    assert PageReader.seen == [("d_ctc01_p1_r72", 1), ("d_ctc01_p2_jpeg", 1)]
    # page 1 holds all 17 gold values, one of them the angle; CTC-01 has no page 2
    assert cases["d_ctc01_p1_r72"].scores["gold"] == 17
    assert cases["d_ctc01_p1_r72"].scores["matched"] == 1
    assert cases["d_ctc01_p2_jpeg"].scores["gold"] == 0
    assert (run.component, run.version) == ("reader-pictures", "page-v1")
