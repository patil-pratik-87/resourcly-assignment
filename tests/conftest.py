import json
import shutil
from pathlib import Path

import pytest

from resourcly.bootstrap import PROJECT_ROOT, Settings

FIXTURE_GOLD = Path(__file__).parent / "fixtures" / "gold"
CTC01 = "nist_ctc_01_asme1_rd"


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
        trace_path=tmp_path / "var" / "traces.sqlite",
        # the text-layer reader needs no model, so the tests can read drawings
        versions={"reader": "textlayer-v0"},
    )


@pytest.fixture
def ctc01() -> dict:
    return json.loads((FIXTURE_GOLD / "drawings" / f"{CTC01}.json").read_text(encoding="utf-8"))
