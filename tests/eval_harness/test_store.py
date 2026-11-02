from pathlib import Path

from resourcly.eval_harness.models import CaseResult, Run
from resourcly.eval_harness.store import SqliteResultStore


def run(run_id: str, version: str = "textlayer-v0") -> Run:
    return Run(
        run_id=run_id,
        component="reader",
        version=version,
        version_hash="abc123",
        split="dev",
        selection={"case_ids": []},
        case_set_hash="c0ffee",
        started_at="2026-11-01T10:00:00Z",
        git_sha="1234567",
        git_dirty=False,
    )


def test_a_run_and_its_cases_read_back_after_reopening(tmp_path: Path) -> None:
    path = tmp_path / "runs" / "evals.sqlite"
    case = CaseResult(
        case_id="nist_ctc_01_asme1_rd",
        stratum="full",
        gold_hash="9f86d0",
        request_id="r1:nist_ctc_01_asme1_rd",
        latency_ms=12.5,
        error=None,
        prediction={"document": {"values": [{"raw": "⌀20"}]}},
        scores={"strict_f1": 0.5},
    )
    with SqliteResultStore.open(path) as store:
        store.start_run(run("r1"))
        store.add_case("r1", case)
        store.finish_run("r1", {"strict_f1": 0.5}, errors=0)

    with SqliteResultStore.open(path) as store:
        saved = store.run("r1")
        cases = store.cases("r1")

    assert saved.summary == {"strict_f1": 0.5}
    assert (saved.n_cases, saved.errors, saved.git_dirty) == (1, 0, False)
    assert saved.finished_at is not None
    assert cases == [case]


def test_runs_list_newest_first_and_filter_by_version(tmp_path: Path) -> None:
    with SqliteResultStore.open(tmp_path / "evals.sqlite") as store:
        for run_id, version in (("r1", "a"), ("r2", "b"), ("r3", "a")):
            store.start_run(run(run_id, version))
            store.finish_run(run_id, {}, errors=0)
        store.start_run(run("r4", "a"))

        assert [r.run_id for r in store.runs()] == ["r4", "r3", "r2", "r1"]
        assert [r.run_id for r in store.runs(component="reader", version="a")] == ["r4", "r3", "r1"]
        assert store.latest("reader", "a").run_id == "r3"
        assert store.latest("reader", "absent") is None
