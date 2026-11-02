"""Compare two runs of one component: metric deltas with a verdict, and per-case changes."""

from dataclasses import dataclass

from resourcly.eval_harness.cases import Case
from resourcly.eval_harness.models import CaseResult, Run
from resourcly.eval_harness.suites import Suite

EPSILON = 1e-9


@dataclass(frozen=True)
class MetricChange:
    name: str
    base: float | None
    candidate: float | None
    verdict: str

    @property
    def delta(self) -> float | None:
        if self.base is None or self.candidate is None:
            return None
        return self.candidate - self.base


@dataclass(frozen=True)
class CaseChange:
    case_id: str
    base: float
    candidate: float

    @property
    def delta(self) -> float:
        return self.candidate - self.base


@dataclass(frozen=True)
class Comparison:
    metrics: list[MetricChange]
    cases: list[CaseChange]
    warnings: list[str]

    @property
    def worse(self) -> bool:
        """The primary metric, listed first, went down."""
        return bool(self.metrics) and self.metrics[0].verdict == "worse"


def compare_runs(
    suite: Suite,
    gold: dict[str, Case],
    base: Run,
    base_cases: list[CaseResult],
    candidate: Run,
    candidate_cases: list[CaseResult],
    force: bool = False,
) -> Comparison:
    """Score both runs' stored answers against the current gold, on the cases both ran.

    Both sides are scored the same way on the same cases, so the verdict holds even when the gold
    changed after a run. Runs on other splits or other cases are refused, since their numbers do
    not measure the same thing; with `force`, a case only one run has, or one with no gold now, is
    left out with a warning. A metric is better when it rises; any change counts. The first is
    the primary one.
    """
    if base.component != candidate.component:
        raise ValueError(f"cannot compare a {base.component} run with a {candidate.component} run")
    before = {case.case_id: case for case in base_cases}
    after = {case.case_id: case for case in candidate_cases}
    if not force and (base.split != candidate.split or before.keys() != after.keys()):
        raise ValueError(
            f"the runs ran on different cases: {len(before)} {base.split} and"
            f" {len(after)} {candidate.split}; --force compares the cases both ran"
        )
    warnings = [
        f"only in {side}: {', '.join(sorted(only))}"
        for side, only in (
            ("base", before.keys() - after.keys()),
            ("candidate", after.keys() - before.keys()),
        )
        if only
    ]
    shared = sorted(before.keys() & after.keys())
    gone = [case_id for case_id in shared if case_id not in gold]
    if gone:
        warnings.append(f"no gold now for {', '.join(gone)}")
    scored = [case_id for case_id in shared if case_id in gold]
    if not scored:
        raise ValueError("the runs share no case that has gold now")
    old = {c: suite.score(gold[c], before[c].prediction) for c in scored}
    new = {c: suite.score(gold[c], after[c].prediction) for c in scored}
    old_summary = suite.summarise([(gold[c].stratum, old[c]) for c in scored])
    new_summary = suite.summarise([(gold[c].stratum, new[c]) for c in scored])
    return Comparison(
        metrics=[_metric(name, old_summary, new_summary) for name in suite.metrics],
        cases=[CaseChange(c, old[c]["case_score"], new[c]["case_score"]) for c in scored],
        warnings=warnings,
    )


def _metric(name: str, base: dict, candidate: dict) -> MetricChange:
    old, new = base.get(name), candidate.get(name)
    gain = None if old is None or new is None else new - old
    if gain is None:
        verdict = "not measured"
    elif gain > EPSILON:
        verdict = "better"
    elif -gain > EPSILON:
        verdict = "worse"
    else:
        verdict = "no change"
    return MetricChange(name, old, new, verdict)
