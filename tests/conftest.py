import json
import shutil
from pathlib import Path

import pytest

FIXTURE_GOLD = Path(__file__).parent / "fixtures" / "gold"
CTC01 = "nist_ctc_01_asme1_rd"


@pytest.fixture
def gold_dir(tmp_path: Path) -> Path:
    target = tmp_path / "gold"
    shutil.copytree(FIXTURE_GOLD, target)
    return target


@pytest.fixture
def ctc01() -> dict:
    return json.loads((FIXTURE_GOLD / "drawings" / f"{CTC01}.json").read_text(encoding="utf-8"))
