import json
import sqlite3
import threading
from pathlib import Path

from resourcly.models import TraceEvent

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    request_id TEXT NOT NULL,
    step TEXT NOT NULL,
    called TEXT NOT NULL,
    input TEXT NOT NULL,
    output TEXT NOT NULL,
    error TEXT,
    started_at TEXT NOT NULL,
    duration_ms REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS events_request ON events (request_id);
"""


class SqliteTraceAdapter:
    """Request traces in one SQLite file. One connection, shared by the API's worker threads."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.executescript(SCHEMA)
        self._lock = threading.Lock()

    def record(self, event: TraceEvent) -> None:
        row = event.model_dump()
        row["input"] = json.dumps(row["input"], ensure_ascii=False)
        row["output"] = json.dumps(row["output"], ensure_ascii=False)
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO events (request_id, step, called, input, output, error, started_at,"
                " duration_ms) VALUES (:request_id, :step, :called, :input, :output, :error,"
                " :started_at, :duration_ms)",
                row,
            )

    def find(self, request_id: str) -> list[TraceEvent]:
        with self._lock:
            rows = self._db.execute(
                "SELECT request_id, step, called, input, output, error, started_at, duration_ms"
                " FROM events WHERE request_id = ? ORDER BY id",
                (request_id,),
            ).fetchall()
        return [
            TraceEvent(
                request_id=request_id,
                step=step,
                called=called,
                input=json.loads(input_),
                output=json.loads(output),
                error=error,
                started_at=started_at,
                duration_ms=duration_ms,
            )
            for request_id, step, called, input_, output, error, started_at, duration_ms in rows
        ]

    def close(self) -> None:
        with self._lock:
            self._db.close()
