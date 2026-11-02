import json
from pathlib import Path

import pytest

from resourcly.bootstrap import Settings, open_services
from resourcly.eval_harness.cases import reader_cases
from tests.conftest import CTC01


@pytest.fixture
def split_gold(gold_dir: Path, ctc01: dict) -> Path:
    partial = gold_dir / "partial" / "partial_a.json"
    partial.parent.mkdir()
    partial.write_text(json.dumps({**ctc01, "drawing": "partial_a"}), encoding="utf-8")
    (gold_dir / "splits.toml").write_text(
        f'[reader]\ndev = ["{CTC01}", "nist_ctc_02_asme1_rc"]\ntest = ["partial_a"]\n',
        encoding="utf-8",
    )
    return gold_dir


def test_reader_cases_are_the_gold_files_the_split_names(
    split_gold: Path, settings: Settings, ctc01: dict, caplog: pytest.LogCaptureFixture
) -> None:
    with open_services(settings) as services:
        dev = reader_cases(services, "dev")
        test = reader_cases(services, "test")

    assert [(c.case_id, c.split, c.stratum) for c in dev] == [(CTC01, "dev", "full")]
    assert dev[0].gold == ctc01
    assert [(c.case_id, c.split, c.stratum) for c in test] == [("partial_a", "test", "partial")]
    assert "nist_ctc_02_asme1_rc has no gold file; skipped" in caplog.text


def test_all_takes_every_gold_file_including_unsplit_ones(
    split_gold: Path, settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    (split_gold / "splits.toml").write_text(
        '[reader]\ndev = ["partial_a", "nist_ctc_02_asme1_rc"]\n', encoding="utf-8"
    )

    with open_services(settings) as services:
        cases = reader_cases(services, "all")

    assert [(c.case_id, c.split) for c in cases] == [(CTC01, "unsplit"), ("partial_a", "dev")]
    assert "has no gold file" not in caplog.text


def test_unreadable_gold_is_skipped_with_a_warning(
    split_gold: Path, settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    (split_gold / "partial" / "partial_a.json").write_text("{not json", encoding="utf-8")

    with open_services(settings) as services:
        cases = reader_cases(services, "test")

    assert cases == []
    assert "partial_a gold has 1 issue(s); skipped" in caplog.text


def test_the_gold_hash_changes_with_the_gold(split_gold: Path, settings: Settings) -> None:
    with open_services(settings) as services:
        before = reader_cases(services, "dev")[0].gold_hash
        path = split_gold / "drawings" / f"{CTC01}.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        document["values"][0]["meaning"] += " Checked."
        path.write_text(json.dumps(document), encoding="utf-8")
        after = reader_cases(services, "dev")[0].gold_hash

    assert before != after


def test_a_split_that_splits_toml_does_not_name_is_refused(
    split_gold: Path, settings: Settings
) -> None:
    with open_services(settings) as services:
        with pytest.raises(LookupError, match="no reader split 'tset'; use dev, test or all"):
            reader_cases(services, "tset")
