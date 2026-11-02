import json
import os
import re
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner, Result

from resourcly.bootstrap import PROJECT_ROOT, READERS, Implementation
from resourcly.eval_harness.cli import app
from resourcly.eval_harness.models import Run
from resourcly.eval_harness.store import SqliteResultStore
from tests.conftest import CTC01


@pytest.fixture
def evals(eval_gold: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RESOURCLY_TRACE_DB", str(tmp_path / "traces.sqlite"))
    monkeypatch.setenv("RESOURCLY_GOLD_DIR", str(eval_gold))
    monkeypatch.setenv("RESOURCLY_SPLITS", str(eval_gold / "splits.toml"))

    def invoke(*args: str) -> Result:
        return CliRunner().invoke(app, ["--store", str(tmp_path / "evals.sqlite"), *args])

    return invoke


def run_id(result: Result) -> str:
    return next(line.split()[1] for line in result.output.splitlines() if line.startswith("run "))


def test_run_prints_the_selection_progress_and_summary_and_lists_the_run(evals) -> None:
    result = evals("run", "reader", "--version", "textlayer-v0")

    assert result.exit_code == 0, result.output
    assert "selected 1 of 1 dev cases\n" in result.output
    assert f"[1/1] {CTC01}  case_score 0.160" in result.output
    assert re.search(r"f1 +\(primary\) +0\.160", result.output)
    listed = evals("list", "runs")
    assert run_id(result) in listed.output
    assert "textlayer-v0" in listed.output


def test_run_limit_runs_the_first_cases_of_the_split(evals) -> None:
    result = evals("run", "reader", "--version", "textlayer-v0", "--split", "all", "--limit", "1")
    refused = evals("run", "reader", "--version", "textlayer-v0", "--limit", "0")

    assert result.exit_code == 0, result.output
    assert "selected 1 of 2 all cases\n" in result.output
    assert f"[1/1] {CTC01}" in result.output
    assert refused.exit_code == 2


def test_show_lists_the_cases_of_a_run_and_explains_one(evals) -> None:
    rid = run_id(evals("run", "reader", "--version", "textlayer-v0", "--split", "all"))

    shown = evals("show", rid)
    failures = evals("show", rid, "--failures")
    detail = evals("show", rid, "--case", CTC01)

    assert shown.exit_code == 0, shown.output
    assert "NotFound: no drawing named partial_a" in shown.output
    assert "--request" not in shown.output
    assert "partial_a" in failures.output
    assert "missed gold records (17)" in detail.output
    assert "page 1  diameter  '⌀35.2 / ⌀34.8'  value [34.8, 35.2]  unit mm" in detail.output
    assert "extra predictions (4)" in detail.output
    assert "page 1  title_block  'NIST PMI Test Models - 2012'" in detail.output


def drop_rev_d(gold_dir: Path) -> None:
    path = gold_dir / "drawings" / f"{CTC01}.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["values"] = [v for v in document["values"] if v["raw"] != "Rev D"]
    path.write_text(json.dumps(document), encoding="utf-8")


class BlankReader:
    def read(self, drawing: str, progress=None) -> dict:
        return {"drawing": drawing, "page_count": 1, "title_block": {}, "values": []}


@pytest.fixture
def blank_reader(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A version blank-v0 whose reader finds nothing, beside the committed versions."""
    versions = tmp_path / "versions"
    shutil.copytree(PROJECT_ROOT / "versions", versions)
    (versions / "reader" / "blank-v0.toml").write_text('impl = "blank"\n', encoding="utf-8")
    monkeypatch.setenv("RESOURCLY_VERSIONS_DIR", str(versions))
    monkeypatch.setitem(READERS, "blank", Implementation(lambda settings, params: BlankReader()))


def test_compare_says_what_got_worse_and_can_fail_on_it(evals, blank_reader) -> None:
    base = run_id(evals("run", "reader", "--version", "textlayer-v0"))
    blank = run_id(evals("run", "reader", "--version", "blank-v0"))

    result = evals("compare", "reader", base, blank)
    failing = evals("compare", "reader", base, blank, "--fail-if-worse")
    by_version = evals("compare", "reader", "textlayer-v0", "blank-v0")

    assert result.exit_code == 0, result.output
    assert re.search(r"f1 +\(primary\) +0\.160 +0\.000 +\-0\.160 +worse", result.output)
    assert f"{CTC01}  0.160 -> 0.000  -0.160" in result.output
    assert failing.exit_code == 1
    assert "f1 got worse" in failing.output
    assert f"base       {base}" in by_version.output
    assert f"candidate  {blank}" in by_version.output
    assert "split dev  1 case(s)" in by_version.output


def test_compare_scores_both_runs_on_the_current_gold(evals, eval_gold: Path) -> None:
    base = run_id(evals("run", "reader", "--version", "textlayer-v0"))
    drop_rev_d(eval_gold)
    candidate = run_id(evals("run", "reader", "--version", "textlayer-v0"))

    result = evals("compare", "reader", base, candidate, "--fail-if-worse")

    assert result.exit_code == 0, result.output
    assert re.search(r"f1 +\(primary\) +0\.083 +0\.083 +\+0\.000 +no +change", result.output)
    assert "0 of 1 case(s) changed case_score" in result.output
    assert CTC01 not in result.output
    assert "warning" not in result.output


def test_a_version_stands_for_its_latest_run_on_every_case_of_a_split(evals, blank_reader) -> None:
    full = run_id(evals("run", "reader", "--version", "textlayer-v0", "--split", "all"))
    evals("run", "reader", "--version", "textlayer-v0", "--split", "all", "--case-id", CTC01)
    blank = run_id(evals("run", "reader", "--version", "blank-v0", "--split", "all"))
    evals("run", "reader", "--version", "blank-v0", "--split", "all", "--limit", "1")

    result = evals("compare", "reader", "textlayer-v0", "blank-v0")

    assert result.exit_code == 0, result.output
    assert f"base       {full}" in result.output
    assert f"candidate  {blank}" in result.output
    assert "warning" not in result.output


def test_a_version_with_only_partial_runs_cannot_stand_for_a_run(evals) -> None:
    evals("run", "reader", "--version", "textlayer-v0", "--case-id", CTC01)

    result = evals("compare", "reader", "textlayer-v0", "textlayer-v0")

    assert result.exit_code == 1
    assert (
        "error: 'textlayer-v0' is neither a run id nor a version with a full run" in result.output
    )


def test_compare_refuses_runs_on_other_cases_unless_forced(evals, blank_reader) -> None:
    base = run_id(evals("run", "reader", "--version", "textlayer-v0", "--split", "all"))
    blank = run_id(evals("run", "reader", "--version", "blank-v0"))

    refused = evals("compare", "reader", base, blank)
    forced = evals("compare", "reader", base, blank, "--force")

    assert refused.exit_code == 1
    assert "error: the runs ran on different cases: 2 all and 1 dev" in refused.output
    assert forced.exit_code == 0, forced.output
    assert "warning: only in base: partial_a" in forced.output


def test_runs_that_share_no_case_are_not_compared(evals, blank_reader) -> None:
    base = run_id(evals("run", "reader", "--version", "textlayer-v0", "--split", "test"))
    blank = run_id(evals("run", "reader", "--version", "blank-v0", "--split", "dev"))

    result = evals("compare", "reader", base, blank, "--force")

    assert result.exit_code == 1
    assert "error: the runs share no case that has gold now" in result.output


def test_list_shows_versions_and_cases(evals) -> None:
    evals("run", "reader", "--version", "textlayer-v0")

    versions = evals("list", "versions", "reader").output
    cases = evals("list", "cases", "reader", "--split", "all").output

    textlayer = next(line for line in versions.splitlines() if "textlayer-v0" in line)
    assert textlayer.split()[1:3] == ["textlayer-v0", "textlayer"]
    assert "1 run(s)" in textlayer
    assert f"{CTC01}  dev    full" in cases
    assert "partial_a             test   partial" in cases


def test_show_out_writes_markdown_tables_of_the_named_runs(evals, tmp_path: Path) -> None:
    dev = run_id(evals("run", "reader", "--version", "textlayer-v0"))
    named = run_id(
        evals("run", "reader", "--version", "textlayer-v0", "--split", "all", "--case-id", CTC01)
    )
    out = tmp_path / "eval-results.md"

    result = evals("show", dev, named, "--out", str(out))

    text = out.read_text(encoding="utf-8")
    assert result.exit_code == 0, result.output
    assert text.count("\n## ") == 2
    assert f"## reader textlayer-v0 on dev: {dev}" in text
    assert f"## reader textlayer-v0 on all (--case-id {CTC01}): {named}" in text
    assert "| metric | value |\n| --- | --- |\n| f1 (primary) | 0.160 |" in text
    assert f"| {CTC01} | full | 0.160 | 19 | 6 | 2 |  |" in text


def test_check_fails_on_a_case_in_two_splits_and_warns_about_missing_gold(
    evals, eval_gold: Path
) -> None:
    clean = evals("check")
    (eval_gold / "splits.toml").write_text(
        f'[reader]\ndev = ["{CTC01}", "nist_ftc_06_asme1_rd"]\ntest = ["{CTC01}"]\n',
        encoding="utf-8",
    )
    broken = evals("check")

    assert clean.exit_code == 0, clean.output
    assert f"ok    reader {CTC01} (full, dev)" in clean.output
    assert broken.exit_code == 1
    assert f"error: reader {CTC01} is in more than one split: dev, test" in broken.output
    assert (
        "warning: reader nist_ftc_06_asme1_rd is in the dev split but has no gold" in broken.output
    )
    assert "warning: reader partial_a has gold but is in no split" in broken.output


def test_the_committed_gold_and_splits_pass_the_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RESOURCLY_TRACE_DB", str(tmp_path / "traces.sqlite"))
    result = CliRunner().invoke(app, ["--store", str(tmp_path / "e.sqlite"), "check"])

    assert result.exit_code == 0, result.output


def test_running_a_component_with_no_such_version_is_a_short_error(evals) -> None:
    result = evals("run", "reader", "--version", "v1")

    assert result.exit_code == 1
    assert "error: no reader version 'v1'" in result.output
    assert result.exception is None or isinstance(result.exception, SystemExit)


def test_a_version_with_an_unknown_setting_is_a_short_error(evals, blank_reader) -> None:
    versions = Path(os.environ["RESOURCLY_VERSIONS_DIR"])
    (versions / "reader" / "typo.toml").write_text('impl = "textlayer"\nmin_words = 3\n')

    result = evals("run", "reader", "--version", "typo")

    assert result.exit_code == 1
    assert "error: reader version 'typo': textlayer takes no setting min_words" in result.output
    assert result.exception is None or isinstance(result.exception, SystemExit)


def test_a_mistyped_split_is_a_short_error_and_stores_no_run(evals) -> None:
    result = evals("run", "reader", "--version", "textlayer-v0", "--split", "tset")

    assert result.exit_code == 1
    assert "error: no reader split 'tset'; use dev, test or all" in result.output
    assert evals("list", "runs").output.count("reader-") == 0


def test_compare_warns_about_a_version_file_broken_since_its_runs(evals, blank_reader) -> None:
    base = run_id(evals("run", "reader", "--version", "textlayer-v0"))
    blank = run_id(evals("run", "reader", "--version", "blank-v0"))
    versions = Path(os.environ["RESOURCLY_VERSIONS_DIR"]) / "reader"
    (versions / "textlayer-v0.toml").write_text('impl = "vlm"\n', encoding="utf-8")
    (versions / "blank-v0.toml").write_text("impl = \n", encoding="utf-8")

    result = evals("compare", "reader", "textlayer-v0", "blank-v0")

    assert result.exit_code == 0, result.output
    assert f"base       {base}" in result.output
    assert f"candidate  {blank}" in result.output
    assert "warning: textlayer-v0 can't be loaded now ('vlm' is not a reader" in result.output
    assert "warning: blank-v0 can't be loaded now (blank-v0.toml is not valid TOML" in result.output


def test_list_runs_says_unfinished_only_for_a_run_that_did_not_finish(
    evals, tmp_path: Path
) -> None:
    partial_only = run_id(evals("run", "reader", "--version", "textlayer-v0", "--split", "test"))
    with SqliteResultStore.open(tmp_path / "evals.sqlite") as store:
        store.start_run(
            Run("reader-cut", "reader", "textlayer-v0", "h", "dev", {}, "c", "now", "1", False)
        )

    rows = {line.split()[0]: line for line in evals("list", "runs").output.splitlines()}

    assert "f1 -" in rows[partial_only]
    assert "unfinished" in rows["reader-cut"]


def test_show_needs_one_run_id_without_out(evals) -> None:
    result = evals("show", "a", "b")

    assert result.exit_code == 1
    assert result.output.strip() == "error: give one run id, or --out FILE for many"


def gold_value(gold_dir: Path, raw: str, change) -> None:
    path = gold_dir / "drawings" / f"{CTC01}.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    change(next(v for v in document["values"] if v["raw"] == raw))
    path.write_text(json.dumps(document), encoding="utf-8")


def test_check_runs_the_gold_rules_the_models_leave_out(evals, eval_gold: Path) -> None:
    # The package models accept limits on a datum symbol, since a reading may carry them; gold not
    gold_value(eval_gold, "A", lambda v: v.update(limits={"lower": 0, "upper": 1}))

    result = evals("check")

    assert result.exit_code == 1
    assert f"error: reader {CTC01} gold: value ctc01-" in result.output
    assert "a none value takes no limits" in result.output


def test_check_runs_the_rules_beyond_the_models(evals, eval_gold: Path) -> None:
    gold_value(eval_gold, "⌀25 ±0.15", lambda v: v.update(raw=v.pop("raw")))

    result = evals("check")

    assert result.exit_code == 1
    assert f"error: reader {CTC01} gold: value ctc01-" in result.output
    assert "keys out of schema order" in result.output


def test_check_reports_a_bad_value_once_not_once_per_checker(evals, eval_gold: Path) -> None:
    gold_value(eval_gold, "⌀25 ±0.15", lambda v: v.update(confidence="high"))

    result = evals("check")

    assert result.exit_code == 1
    assert result.output.count(f"error: reader {CTC01} gold:") == 1
    assert "confidence" in result.output


def test_check_counts_the_values_below_the_review_confidence(evals, eval_gold: Path) -> None:
    gold_value(eval_gold, "⌀25 ±0.15", lambda v: v.update(confidence=0.5))

    result = evals("check")

    assert result.exit_code == 0, result.output
    assert (
        f"ok    reader {CTC01} (full, dev): 1 page(s), 15 features, 19 values,"
        " 1 below confidence 0.7"
    ) in result.output
