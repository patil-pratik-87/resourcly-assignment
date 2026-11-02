"""The ports of the eval harness, the parts that an eval can swap without changing the harness."""

from typing import Any, Protocol

from resourcly.eval_harness.models import CaseResult, Run


class ResultStorePort(Protocol):
    """Runs and their case results, kept with the raw predictions so a run can be scored again."""

    def start_run(self, run: Run) -> None: ...

    def add_case(self, run_id: str, case: CaseResult) -> None: ...

    def finish_run(self, run_id: str, summary: dict[str, Any], errors: int) -> None:
        """Store the summary and error count and mark the run finished."""
        ...

    def run(self, run_id: str) -> Run:
        """The run, or LookupError."""
        ...

    def cases(self, run_id: str) -> list[CaseResult]:
        """The run's case results, ordered by case id."""
        ...

    def runs(
        self, component: str | None = None, version: str | None = None, limit: int = 1000
    ) -> list[Run]:
        """Runs, newest first."""
        ...

    def latest(self, component: str, version: str) -> Run | None:
        """The newest finished run of a version."""
        ...
