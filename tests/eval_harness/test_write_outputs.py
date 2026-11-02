import json
from pathlib import Path

import pytest

import write_outputs
from resourcly.eval_harness.store import SqliteResultStore
from tests.conftest import CTC01
from tests.eval_harness.test_cli import run_id


def test_the_outputs_are_the_documents_of_the_latest_full_run(
    evals, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    evals("run", "reader", "--version", "textlayer-v0", "--split", "all", "--limit", "1")
    full = run_id(evals("run", "reader", "--version", "textlayer-v0", "--split", "all"))
    store, out = tmp_path / "evals.sqlite", tmp_path / "outputs"

    write_outputs.main(["--version", "textlayer-v0", "--store", str(store), "--out", str(out)])

    with SqliteResultStore.open(store) as opened:
        cases = {case.case_id: case for case in opened.cases(full)}
    written = out / f"{CTC01}.json"
    expected = json.dumps(cases[CTC01].prediction["document"], indent=2, ensure_ascii=False)
    assert written.read_text(encoding="utf-8") == expected + "\n"
    assert sorted(path.name for path in out.iterdir()) == [f"{CTC01}.json", "partial_a.json"]
    assert f"wrote 2 file(s) to {out} from run {full}" in capsys.readouterr().out


def test_without_a_full_run_it_says_how_to_make_one(evals, tmp_path: Path) -> None:
    store = tmp_path / "evals.sqlite"
    evals("run", "reader", "--version", "textlayer-v0", "--split", "all", "--limit", "1")

    with pytest.raises(SystemExit, match="evals run reader --version textlayer-v0 --split all"):
        write_outputs.main(["--version", "textlayer-v0", "--store", str(store)])
