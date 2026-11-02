"""The eval loop: open the services for a version, take its cases, call, store, score, summarise."""

import hashlib
import logging
import random
import secrets
import subprocess
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from resourcly.bootstrap import PROJECT_ROOT, Settings, load_version, open_services
from resourcly.eval_harness.models import Case, CaseResult, Run, now
from resourcly.eval_harness.store import SqliteResultStore
from resourcly.eval_harness.suites import SUITES

log = logging.getLogger(__name__)

SEED = 0  # the seed of the sample a --limit run takes


def run(
    component: str,
    version: str,
    *,
    settings: Settings,
    store: SqliteResultStore,
    split: str = "dev",
    case_ids: tuple[str, ...] = (),
    limit: int | None = None,
    on_start: Callable[[Run, list[Case], int], None] | None = None,
    on_case: Callable[[CaseResult], None] | None = None,
) -> Run:
    """Run one version of a component on every gold case of a split, only the named ones, or a
    sample of `limit` of them, and store the result. `compare` scores the stored answers again
    on the current gold.

    A case whose call fails is stored with its error and scored as if it returned nothing.
    """
    suite = SUITES[component]
    resolved = load_version(settings, suite.part, version)
    with open_services(settings.with_version(suite.part, version)) as services:
        pool = suite.load(services, split)
        chosen = _choose(pool, case_ids)
        if limit is not None:
            chosen = sample(chosen, limit)
        if not chosen:
            raise ValueError(
                f"no {component} case of the {split} split was selected; nothing was stored"
            )
        run_id = _new_run_id(component)
        started = Run(
            run_id=run_id,
            component=component,
            version=version,
            version_hash=resolved.hash,
            split=split,
            case_ids=[] if len(chosen) == len(pool) else [case.case_id for case in chosen],
            case_set_hash=case_set_hash(chosen),
            started_at=now(),
            **_git(),
        )
        store.start_run(started)
        if on_start:
            on_start(started, chosen, len(pool))
        results = []
        for case in chosen:
            request_id = f"{run_id}:{case.case_id}"
            began = time.perf_counter()
            try:
                prediction, error = suite.call(services, case, request_id), None
            except Exception as exc:
                prediction, error = None, f"{type(exc).__name__}: {exc}"
            result = CaseResult(
                case_id=case.case_id,
                stratum=case.stratum,
                gold_hash=case.gold_hash,
                request_id=request_id,
                latency_ms=round((time.perf_counter() - began) * 1000, 1),
                error=error,
                prediction=prediction,
                scores=suite.score(case, prediction),
            )
            results.append((case, result))
            store.add_case(run_id, result)
            if on_case:
                on_case(result)
    return _finish(store, run_id, results)


def _finish(store: SqliteResultStore, run_id: str, results: list[tuple[Case, CaseResult]]) -> Run:
    suite = SUITES[store.run(run_id).component]
    summary = suite.summarise([(result.stratum, result.scores) for _, result in results])
    errors = sum(1 for _, result in results if result.error)
    store.finish_run(run_id, summary, errors)
    return store.run(run_id)


def case_set_hash(cases: list[Case]) -> str:
    text = "\n".join(sorted(f"{case.case_id}:{case.gold_hash}" for case in cases))
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def _choose(pool: list[Case], case_ids: tuple[str, ...]) -> list[Case]:
    if not case_ids:
        return pool
    known = {case.case_id for case in pool}
    for missing in sorted(set(case_ids) - known):
        log.warning("%s is not a case in this split; skipped", missing)
    return [case for case in pool if case.case_id in case_ids]


def sample(cases: list[Case], limit: int) -> list[Case]:
    """`limit` of the cases, spread over the strata in proportion to their size, in case id order.

    Each stratum gives one case before any gives a second, so a small run sees every kind of
    case. Each is shuffled with a fixed seed, so a run takes the same cases each time.
    """
    if limit >= len(cases):
        return cases
    rng = random.Random(SEED)
    strata: dict[str, list[Case]] = {}
    for case in cases:
        strata.setdefault(case.stratum, []).append(case)
    shuffled = {name: rng.sample(group, len(group)) for name, group in sorted(strata.items())}
    taken = dict.fromkeys(shuffled, 0)
    while sum(taken.values()) < limit:
        name = min(
            (name for name in shuffled if taken[name] < len(shuffled[name])),
            key=lambda name: (taken[name] / len(shuffled[name]), name),
        )
        taken[name] += 1
    picked = [case for name, group in shuffled.items() for case in group[: taken[name]]]
    return sorted(picked, key=lambda case: case.case_id)


def _new_run_id(component: str) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{component}-{stamp}-{secrets.token_hex(2)}"


def _git() -> dict[str, Any]:
    def git(*args: str) -> str:
        done = subprocess.run(
            ["git", "-C", str(PROJECT_ROOT), *args], capture_output=True, text=True, check=False
        )
        return done.stdout.strip() if done.returncode == 0 else ""

    return {
        "git_sha": git("rev-parse", "--short", "HEAD") or "unknown",
        "git_dirty": bool(git("status", "--porcelain")),
    }
