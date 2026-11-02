import json
import shutil
from pathlib import Path

import pymupdf
import pytest

from resourcly.bootstrap import PROJECT_ROOT, Settings

FIXTURE_GOLD = Path(__file__).parent / "fixtures" / "gold"
CTC01 = "nist_ctc_01_asme1_rd"


def png(width: int = 40, height: int = 30) -> bytes:
    """A small grey PNG, standing in for a photo."""
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, width, height), False)
    pixmap.clear_with(200)
    return pixmap.tobytes("png")


@pytest.fixture(autouse=True)
def model_free_versions(monkeypatch: pytest.MonkeyPatch) -> None:
    """The app's default reader, failure finder and answer run models; tests use model-free ones.

    The router's stub is set by the tests that run the app's router.
    """
    monkeypatch.setenv("RESOURCLY_READER_VERSION", "textlayer-v0")
    monkeypatch.setenv("RESOURCLY_FAILURE_VERSION", "shuffled-v0")
    monkeypatch.setenv("RESOURCLY_ANSWER_VERSION", "captions-v0")


@pytest.fixture
def gold_dir(tmp_path: Path) -> Path:
    target = tmp_path / "gold"
    shutil.copytree(FIXTURE_GOLD, target)
    return target


@pytest.fixture
def settings(gold_dir: Path, tmp_path: Path) -> Settings:
    return Settings(
        gold_dir=gold_dir,
        splits_path=gold_dir / "splits.toml",
        drawings_dir=PROJECT_ROOT / "data" / "drawings",
        chat_ui_dist=tmp_path / "no-chat-ui",
        annotation_ui_dist=tmp_path / "no-annotation-ui",
        trace_path=tmp_path / "var" / "traces.sqlite",
        uploads_dir=tmp_path / "var" / "uploads",
        demo_dir=None,
        # these versions need no model, so the tests can run them
        versions={
            "reader": "textlayer-v0",
            "router": "stub-v0",
            "failure": "shuffled-v0",
            "answer": "captions-v0",
        },
    )


@pytest.fixture
def ctc01() -> dict:
    return json.loads((FIXTURE_GOLD / "drawings" / f"{CTC01}.json").read_text(encoding="utf-8"))
