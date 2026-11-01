"""The eval loop: open the services for a version, take its cases, call, store, score, summarise."""

import hashlib
import logging
import secrets
import subprocess
import time
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from resourcly.bootstrap import PROJECT_ROOT, Settings, load_version, open_services
from resourcly.evals.cases import Case
from resourcly.evals.models import CaseResult, Run
from resourcly.evals.ports import ResultStorePort
from resourcly.evals.suites import SUITES, Suite

log = logging.getLogger(__name__)


def run(
    component: str,
    version: str,
    *,
    settings: Settings,
    store: ResultStorePort,
    split: str = "dev",
    case_ids: tuple[str, ...] = (),
    note: str | None = None,
    on_start: Callable[[Run, list[Case], int], None] | None = None,
    on_case: Callable[[CaseResult], None] | None = None,
) -> Run:
    """Run one version of a component on every gold case of a split, or only the named ones, and
    store the result.

    A case whose call fails is stored with its error and scored as if it returned nothing.
    """
    suite = SUITES[component]
    resolved = load_version(settings, component, version)
    with open_services(settings.with_version(component, version)) as services:
        pool = suite.load(services, split)
        chosen = _choose(pool, case_ids)
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
            selection={"case_ids": list(case_ids)},
            case_set_hash=case_set_hash(chosen),
            started_at=_now(),
            note=note,
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


def rescore(run_id: str, *, settings: Settings, store: ResultStorePort) -> Run:
    """Score a run's stored predictions against the current gold as a new run; nothing is called."""
    old = store.run(run_id)
    suite = SUITES[old.component]
    current = _current_cases(suite, settings)
    results = []
    for stored in store.cases(run_id):
        case = current.get(stored.case_id)
        if case is None:
            log.warning("%s has no gold now; left out of the rescore", stored.case_id)
            continue
        results.append((case, _score_again(suite, case, stored)))
    if not results:
        raise ValueError(f"no case of run {run_id} has gold now; nothing was stored")
    new_id = _new_run_id(old.component)
    store.start_run(
        replace(
            old,
            run_id=new_id,
            case_set_hash=case_set_hash([case for case, _ in results]),
            started_at=_now(),
            rescored_from=old.run_id,
            note=f"rescore of {old.run_id}",
            finished_at=None,
            summary=None,
            n_cases=0,
            errors=0,
            **_git(),
        )
    )
    for _, result in results:
        store.add_case(new_id, result)
    return _finish(store, new_id, results)


def _current_cases(suite: Suite, settings: Settings) -> dict[str, Case]:
    with open_services(settings) as services:
        return {case.case_id: case for case in suite.load(services, "all")}


def _score_again(suite: Suite, case: Case, stored: CaseResult) -> CaseResult:
    scores = suite.score(case, stored.prediction)
    return replace(stored, stratum=case.stratum, gold_hash=case.gold_hash, scores=scores)


def _finish(store: ResultStorePort, run_id: str, results: list[tuple[Case, CaseResult]]) -> Run:
    suite = SUITES[store.run(run_id).component]
    summary = suite.summarise([(case, result.prediction) for case, result in results])
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


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
