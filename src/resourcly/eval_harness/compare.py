"""Compare two runs of one component: metric deltas with a verdict, and per-case changes."""

from dataclasses import dataclass

from resourcly.eval_harness.models import CaseResult, Run

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
    base: Run
    candidate: Run
    metrics: list[MetricChange]
    cases: list[CaseChange]
    warnings: list[str]

    @property
    def worse(self) -> bool:
        """The primary metric, listed first, went down."""
        return bool(self.metrics) and self.metrics[0].verdict == "worse"

    @property
    def comparable(self) -> bool:
        return bool(self.metrics) and self.metrics[0].verdict != "no verdict"


def compare_runs(
    base: Run,
    base_cases: list[CaseResult],
    candidate: Run,
    candidate_cases: list[CaseResult],
    metrics: tuple[str, ...],
    primary: str,
) -> Comparison:
    """A metric is better when it rises; any change counts.

    Only runs on the same case set, which includes the gold of each case, get a verdict: they
    compare their stored summaries. Otherwise no metric gets a verdict, and the warnings say to
    rescore the older run on the current gold first.
    """
    if base.component != candidate.component:
        raise ValueError(f"cannot compare a {base.component} run with a {candidate.component} run")
    ordered = [primary, *(name for name in metrics if name != primary)]
    before = {case.case_id: case for case in base_cases}
    after = {case.case_id: case for case in candidate_cases}
    shared = sorted(before.keys() & after.keys())
    changed = [
        case_id for case_id in shared if before[case_id].gold_hash != after[case_id].gold_hash
    ]
    warnings = []
    same = base.case_set_hash == candidate.case_set_hash
    if not same and not shared:
        warnings.append("no verdict: the runs share no case")
    elif not same:
        warnings.append(
            "no verdict: the runs ran on different cases or gold; rescore the older run first"
            " with `evals run --rescore RUN_ID`"
        )
    for side, only in (
        ("base", before.keys() - after.keys()),
        ("candidate", after.keys() - before.keys()),
    ):
        if only:
            warnings.append(f"only in {side}: {', '.join(sorted(only))}")
    if changed:
        warnings.append(f"gold changed between the runs for {', '.join(changed)}")
    changes = [
        _metric(name, base.summary or {}, candidate.summary or {})
        if same
        else MetricChange(name, None, None, "no verdict")
        for name in ordered
    ]
    cases = [
        CaseChange(
            case_id,
            before[case_id].scores.get("case_score", 0.0),
            after[case_id].scores.get("case_score", 0.0),
        )
        for case_id in shared
    ]
    return Comparison(base, candidate, changes, cases, warnings)


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
