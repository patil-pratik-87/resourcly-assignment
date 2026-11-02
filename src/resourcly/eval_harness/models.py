"""What a run stores: the run's settings and summary, and one result per case."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Run:
    run_id: str
    component: str
    version: str
    version_hash: str
    split: str
    case_ids: list[str]  # the cases run when not every case of the split ran
    case_set_hash: str
    started_at: str
    git_sha: str
    git_dirty: bool
    finished_at: str | None = None
    n_cases: int = 0
    errors: int = 0
    summary: dict[str, Any] | None = None


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    stratum: str
    gold_hash: str
    request_id: str
    latency_ms: float | None
    error: str | None
    prediction: Any
    scores: dict[str, Any]
