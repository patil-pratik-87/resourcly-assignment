import json
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import asdict, fields
from pathlib import Path
from typing import Any

from resourcly.eval_harness.models import CaseResult, Run, now

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    component TEXT NOT NULL,
    version TEXT NOT NULL,
    version_hash TEXT NOT NULL,
    split TEXT NOT NULL,
    case_ids TEXT NOT NULL,
    case_set_hash TEXT NOT NULL,
    started_at TEXT NOT NULL,
    git_sha TEXT NOT NULL,
    git_dirty INTEGER NOT NULL,
    finished_at TEXT,
    n_cases INTEGER NOT NULL DEFAULT 0,
    errors INTEGER NOT NULL DEFAULT 0,
    summary TEXT
);
CREATE TABLE IF NOT EXISTS cases (
    run_id TEXT NOT NULL REFERENCES runs (run_id),
    case_id TEXT NOT NULL,
    stratum TEXT NOT NULL,
    gold_hash TEXT NOT NULL,
    request_id TEXT NOT NULL,
    latency_ms REAL,
    error TEXT,
    prediction TEXT,
    scores TEXT NOT NULL,
    PRIMARY KEY (run_id, case_id)
);
"""
JSON_COLUMNS = {"case_ids", "summary", "prediction", "scores"}


class SqliteResultStore:
    """Runs and their cases in SQLite: one row per run and one per case, with the raw prediction.

    Keeping the prediction lets `compare` score a run again against new gold without calling the
    component again.
    """

    def __init__(self, db: sqlite3.Connection):
        self.db = db

    @classmethod
    @contextmanager
    def open(cls, path: Path) -> Iterator["SqliteResultStore"]:
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(path)) as db:
            db.row_factory = sqlite3.Row
            db.executescript(SCHEMA)
            columns = {row["name"] for row in db.execute("PRAGMA table_info(runs)")}
            if columns != {field.name for field in fields(Run)}:
                raise ValueError(
                    f"{path} was written by an older harness; move it away to start anew"
                )
            yield cls(db)

    def start_run(self, run: Run) -> None:
        self._insert("runs", asdict(run))

    def add_case(self, run_id: str, case: CaseResult) -> None:
        self._insert("cases", {"run_id": run_id, **asdict(case)})

    def finish_run(self, run_id: str, summary: dict[str, Any], errors: int) -> None:
        with self.db:
            self.db.execute(
                "UPDATE runs SET finished_at = ?, summary = ?, errors = ?,"
                " n_cases = (SELECT count(*) FROM cases WHERE run_id = ?) WHERE run_id = ?",
                (now(), json.dumps(summary, ensure_ascii=False), errors, run_id, run_id),
            )

    def run(self, run_id: str) -> Run:
        row = self.db.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            raise LookupError(f"no run '{run_id}'")
        return _load(Run, row)

    def cases(self, run_id: str) -> list[CaseResult]:
        rows = self.db.execute(
            "SELECT * FROM cases WHERE run_id = ? ORDER BY case_id", (run_id,)
        ).fetchall()
        return [_load(CaseResult, row) for row in rows]

    def runs(
        self, component: str | None = None, version: str | None = None, limit: int = 1000
    ) -> list[Run]:
        rows = self.db.execute(
            "SELECT * FROM runs WHERE (?1 IS NULL OR component = ?1)"
            " AND (?2 IS NULL OR version = ?2) ORDER BY rowid DESC LIMIT ?3",
            (component, version, limit),
        ).fetchall()
        return [_load(Run, row) for row in rows]

    def _insert(self, table: str, row: dict[str, Any]) -> None:
        values = {
            key: json.dumps(value, ensure_ascii=False) if key in JSON_COLUMNS else value
            for key, value in row.items()
        }
        columns = ", ".join(values)
        marks = ", ".join("?" for _ in values)
        with self.db:
            self.db.execute(
                f"INSERT INTO {table} ({columns}) VALUES ({marks})", tuple(values.values())
            )


def _load(kind: type, row: sqlite3.Row) -> Any:
    values = {}
    for field in fields(kind):
        value = row[field.name]
        if field.name in JSON_COLUMNS and value is not None:
            value = json.loads(value)
        elif field.name == "git_dirty":
            value = bool(value)
        values[field.name] = value
    return kind(**values)
