import functools
import logging
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any

import typer

from resourcly.bootstrap import (
    PROJECT_ROOT,
    Settings,
    list_versions,
    load_version,
    open_services,
)
from resourcly.eval_harness import harness
from resourcly.eval_harness.cases import Case, check_gold
from resourcly.eval_harness.compare import EPSILON, compare_runs
from resourcly.eval_harness.models import CaseResult, Run
from resourcly.eval_harness.store import SqliteResultStore
from resourcly.eval_harness.suites import SUITES, Suite

app = typer.Typer(help="Measure each part of the agent on its gold cases.", no_args_is_help=True)

DEFAULT_STORE = PROJECT_ROOT / "runs" / "evals.sqlite"


StorePath = Annotated[
    Path, typer.Option("--store", envvar="RESOURCLY_EVALS_DB", help="SQLite file of the results.")
]
Component = Annotated[str, typer.Argument(help="reader, router or failure")]


@app.callback()
def main(ctx: typer.Context, store: StorePath = DEFAULT_STORE) -> None:
    """The gold and the versions come from the RESOURCLY_* settings, as for the app."""
    logging.basicConfig(format="warning: %(message)s", level=logging.WARNING, force=True)
    ctx.obj = store


def _user_errors(command: Callable[..., None]) -> Callable[..., None]:
    """A missing or invalid version, case, run or file is the user's to fix: one line, exit 1."""

    @functools.wraps(command)
    def wrapped(*args: Any, **kwargs: Any) -> None:
        try:
            command(*args, **kwargs)
        except (LookupError, ValueError) as error:
            typer.echo(f"error: {error}", err=True)
            raise typer.Exit(1) from error

    return wrapped


@app.command()
@_user_errors
def run(
    ctx: typer.Context,
    component: Component,
    version: Annotated[str, typer.Option(help="A file in versions/<component>/.")],
    split: Annotated[str, typer.Option(help="dev, test or all.")] = "dev",
    case_id: Annotated[
        list[str] | None, typer.Option(help="Run only these cases; every case by default.")
    ] = None,
    note: Annotated[str | None, typer.Option(help="Free text stored with the run.")] = None,
) -> None:
    """Run a version of a component on the gold cases of a split."""
    suite = _suite(component)
    progress = {"done": 0, "total": 0}

    def started(run: Run, chosen: list[Case], pool: int) -> None:
        progress["total"] = len(chosen)
        typer.echo(f"selected {len(chosen)} of {pool} {split} cases")
        typer.echo(f"version {run.version}  hash {run.version_hash}  git {_git_label(run)}")

    def finished(result: CaseResult) -> None:
        progress["done"] += 1
        outcome = (
            f"error {result.error}"
            if result.error
            else f"case_score {_num(result.scores['case_score'])}"
        )
        counter = f"[{progress['done']}/{progress['total']}]"
        typer.echo(f"{counter} {result.case_id}  {outcome}  {result.latency_ms:.0f} ms")

    with SqliteResultStore.open(ctx.obj) as store:
        result = harness.run(
            component,
            version,
            settings=Settings.from_env(),
            store=store,
            split=split,
            case_ids=tuple(case_id or ()),
            note=note,
            on_start=started,
            on_case=finished,
        )
    typer.echo(f"run {result.run_id}  (case set {result.case_set_hash}, store {ctx.obj})")
    typer.echo("")
    _summary(suite, result)


@app.command()
@_user_errors
def compare(
    ctx: typer.Context,
    component: Component,
    base: Annotated[str, typer.Argument(help="A run id, or a version for its latest run.")],
    candidate: Annotated[str, typer.Argument(help="A run id, or a version for its latest run.")],
    fail_if_worse: Annotated[bool, typer.Option(help="Exit 1 if the primary got worse.")] = False,
) -> None:
    """Whether the candidate is better or worse than the base, metric by metric and case by case.

    Both runs' stored answers are scored again on the current gold, on the cases both ran.
    """
    suite = _suite(component)
    settings = Settings.from_env()
    with SqliteResultStore.open(ctx.obj) as store:
        runs = [_resolve(store, settings, component, ref) for ref in (base, candidate)]
        with open_services(settings) as services:
            gold = {case.case_id: case for case in suite.load(services, "all")}
        comparison = compare_runs(
            suite,
            gold,
            runs[0],
            store.cases(runs[0].run_id),
            runs[1],
            store.cases(runs[1].run_id),
        )
    for label, run in (("base", runs[0]), ("candidate", runs[1])):
        typer.echo(
            f"{label.ljust(9)}  {run.run_id}  {run.version}  hash {run.version_hash}"
            f"  split {run.split}  {run.n_cases} case(s)"
        )
    typer.echo("")
    rows = [
        [
            f"{m.name} (primary)" if m.name == suite.primary else m.name,
            _num(m.base),
            _num(m.candidate),
            "-" if m.delta is None else f"{m.delta:+.3f}",
            m.verdict,
        ]
        for m in comparison.metrics
    ]
    _table(["metric", "base", "candidate", "delta", "verdict"], rows)
    typer.echo("")
    changed = [c for c in comparison.cases if abs(c.delta) > EPSILON]
    typer.echo(f"{len(changed)} of {len(comparison.cases)} case(s) changed case_score")
    for change in sorted(changed, key=lambda c: (c.delta, c.case_id)):
        typer.echo(
            f"  {change.case_id}  {_num(change.base)} -> {_num(change.candidate)}"
            f"  {change.delta:+.3f}"
        )
    for warning in comparison.warnings:
        typer.echo(f"warning: {warning}", err=True)
    if fail_if_worse and comparison.worse:
        typer.echo(f"{suite.primary} got worse", err=True)
        raise typer.Exit(1)


@app.command()
@_user_errors
def show(
    ctx: typer.Context,
    run_ids: Annotated[
        list[str],
        typer.Argument(help="A run id from `evals list runs`; with --out, any number of them."),
    ],
    case: Annotated[str | None, typer.Option(help="Explain one case against the gold.")] = None,
    failures: Annotated[
        bool, typer.Option(help="Only cases that failed or scored below 1.")
    ] = False,
    out: Annotated[
        Path | None, typer.Option(help="Write Markdown tables of the runs to this file.")
    ] = None,
) -> None:
    """A run's settings, summary and cases, or Markdown tables of runs.

    What a case did and called: `resourcly request <run id>:<case id>`.
    """
    if out is not None:
        if case or failures:
            raise ValueError("--out takes no --case or --failures")
        _report(ctx.obj, run_ids, out)
        return
    if len(run_ids) > 1:
        raise ValueError("give one run id, or --out FILE for many")
    run_id = run_ids[0]
    with SqliteResultStore.open(ctx.obj) as store:
        run = store.run(run_id)
        results = store.cases(run_id)
    suite = SUITES[run.component]
    if case is not None:
        _explain(run, suite, next((r for r in results if r.case_id == case), None), case)
        return
    typer.echo(f"run {run.run_id}  {run.component} {run.version} (hash {run.version_hash})")
    chosen = f"{len(run.case_ids)} chosen case(s)" if run.case_ids else "every case"
    typer.echo(f"split {run.split}, {chosen}, case set {run.case_set_hash}")
    finished = run.finished_at or "-"
    typer.echo(f"started {run.started_at}  finished {finished}  git {_git_label(run)}")
    if run.note:
        typer.echo(f"note {run.note}")
    typer.echo("")
    _summary(suite, run)
    typer.echo("")
    shown = [r for r in results if not failures or r.error or r.scores["case_score"] < 1]
    rows = [
        [
            r.case_id,
            r.stratum,
            _num(r.scores["case_score"]),
            f"{r.latency_ms:.0f} ms" if r.latency_ms is not None else "-",
            r.error or "",
        ]
        for r in shown
    ]
    _table(["case", "stratum", "case_score", "latency", "error"], rows)


def _report(path: Path, run_ids: list[str], out: Path) -> None:
    """Markdown tables of runs, for results that go in the repository."""
    with SqliteResultStore.open(path) as store:
        runs = [store.run(run_id) for run_id in run_ids]
        sections = [_markdown(run, store.cases(run.run_id)) for run in runs]
    text = "# Eval results\n\nWritten by `uv run evals show --out`.\n" + "".join(sections)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    typer.echo(f"wrote {len(runs)} run(s) to {out}")


class Listing(StrEnum):
    versions = "versions"
    cases = "cases"
    runs = "runs"


@app.command("list")
@_user_errors
def list_(
    ctx: typer.Context,
    what: Annotated[Listing, typer.Argument(help="What to list.")],
    component: Annotated[
        str | None, typer.Argument(help="reader, router or failure; cases need one.")
    ] = None,
    split: Annotated[str, typer.Option(help="dev, test or all, for cases.")] = "dev",
    version: Annotated[str | None, typer.Option(help="Only this version's runs.")] = None,
    limit: Annotated[int, typer.Option(help="How many runs.")] = 20,
) -> None:
    """Version files, a component's cases, or runs."""
    if what is Listing.versions:
        _list_versions(ctx.obj, component)
    elif what is Listing.cases:
        if component is None:
            raise ValueError("cases need a component: reader, router or failure")
        _list_cases(component, split)
    else:
        _list_runs(ctx.obj, component, version, limit)


def _list_versions(path: Path, component: str | None) -> None:
    settings = Settings.from_env()
    with SqliteResultStore.open(path) as store:
        rows = [
            [
                version.component,
                version.name,
                version.impl,
                version.hash,
                f"{len(store.runs(version.component, version.name))} run(s)",
                version.description,
            ]
            for name in ([_suite(component).component] if component else list(SUITES))
            for version in list_versions(settings, name)
        ]
    _table(["component", "version", "impl", "hash", "runs", "description"], rows)


def _list_cases(component: str, split: str) -> None:
    with open_services(Settings.from_env()) as services:
        cases = _suite(component).load(services, split)
    _table(
        ["case", "split", "stratum", "gold hash"],
        [[case.case_id, case.split, case.stratum, case.gold_hash] for case in cases],
    )


def _list_runs(path: Path, component: str | None, version: str | None, limit: int) -> None:
    with SqliteResultStore.open(path) as store:
        runs = store.runs(component, version, limit)
    rows = []
    for run in runs:
        primary = SUITES[run.component].primary
        value = (run.summary or {}).get(primary)
        rows.append(
            [
                run.run_id,
                run.version,
                run.split,
                str(run.n_cases),
                str(run.errors),
                f"{primary} {_num(value)}" if run.finished_at else "unfinished",
            ]
        )
    _table(["run", "version", "split", "cases", "errors", "primary"], rows)


@app.command()
@_user_errors
def check(ctx: typer.Context) -> None:
    """Check every gold file and the splits; exit 1 on an error, warn about gaps.

    Drawing gold goes through the package models and the rules beyond them; router and failure gold
    through their row checks; and every split for leaks and gaps.
    """
    with open_services(Settings.from_env()) as services:
        found = check_gold(services)
    for level, message in found:
        typer.echo(f"{'ok   ' if level == 'ok' else level + ':'} {message}")
    errors = sum(1 for level, _ in found if level == "error")
    warnings = sum(1 for level, _ in found if level == "warning")
    typer.echo(f"{errors} error(s), {warnings} warning(s)")
    if errors:
        raise typer.Exit(1)


def _resolve(store: SqliteResultStore, settings: Settings, component: str, ref: str) -> Run:
    """The run a ref names: a run id, or a version for its latest finished run."""
    try:
        run = store.run(ref)
    except LookupError:
        runs = [run for run in store.runs(component, ref) if run.finished_at]
        if not runs:
            raise LookupError(f"'{ref}' is neither a run id nor a version with runs") from None
        run = runs[0]
        _warn_if_edited(settings, component, ref, run)
    if run.component != component:
        raise ValueError(f"run {run.run_id} is a {run.component} run")
    return run


def _warn_if_edited(settings: Settings, component: str, version: str, run: Run) -> None:
    try:
        now = load_version(settings, component, version).hash
    except (LookupError, ValueError) as error:
        typer.echo(f"warning: {version} can't be loaded now ({error})", err=True)
        return
    if now != run.version_hash:
        typer.echo(f"warning: {version} changed since run {run.run_id}", err=True)


def _explain(run: Run, suite: Suite, result: CaseResult | None, case_id: str) -> None:
    if result is None:
        raise LookupError(f"run {run.run_id} has no case '{case_id}'")
    with open_services(Settings.from_env()) as services:
        current = {case.case_id: case for case in suite.load(services, "all")}
    case = current.get(case_id)
    if case is None:
        raise LookupError(f"'{case_id}' has no gold now")
    typer.echo(f"{case_id}  case_score {_num(result.scores['case_score'])}")
    typer.echo(f"request {result.request_id}  (resourcly request {result.request_id})")
    if case.gold_hash != result.gold_hash:
        typer.echo("the gold changed since this run; compared with the current gold")
    if result.error:
        typer.echo(f"error {result.error}")
    for line in suite.explain(case, result.prediction):
        typer.echo(line)


def _markdown(run: Run, results: list[CaseResult]) -> str:
    suite = SUITES[run.component]
    selected = f" ({_selected(run)})" if _selected(run) else ""
    columns = ["case_score", *suite.case_columns]
    cases = [
        [r.case_id, r.stratum, *(_num(r.scores.get(c)) for c in columns), r.error or ""]
        for r in results
    ]
    lines = [
        "",
        f"## {run.component} {run.version} on {run.split}{selected}: {run.run_id}",
        "",
        f"Version hash {run.version_hash}, case set {run.case_set_hash}, git {_git_label(run)}, "
        f"finished {run.finished_at}, {run.errors} error(s) in {run.n_cases} case(s).",
        "",
        *_lines(["metric", "value"], _metric_rows(suite, run), markdown=True),
        "",
        *_lines(["case", "stratum", *columns, "error"], cases, markdown=True),
    ]
    return "\n".join(lines) + "\n"


def _selected(run: Run) -> str | None:
    """How a run picked part of its split, as the run options; None for every case."""
    if run.case_ids:
        return f"--case-id {', '.join(run.case_ids)}"
    return None


def _summary(suite: Suite, run: Run) -> None:
    _table(
        ["metric", "value"],
        [*_metric_rows(suite, run), ["errors", f"{run.errors} of {run.n_cases}"]],
    )


def _metric_rows(suite: Suite, run: Run) -> list[list[str]]:
    summary = run.summary or {}
    return [
        [f"{name} (primary)" if name == suite.primary else name, _num(summary.get(name))]
        for name in suite.metrics
    ]


def _suite(component: str) -> Suite:
    if component not in SUITES:
        raise LookupError(f"'{component}' is not a component; use {', '.join(SUITES)}")
    return SUITES[component]


def _git_label(run: Run) -> str:
    return f"{run.git_sha}{' with local changes' if run.git_dirty else ''}"


def _num(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def _table(headers: list[str], rows: list[list[str]]) -> None:
    for line in _lines(headers, rows):
        typer.echo(line)


def _lines(headers: list[str], rows: list[list[str]], markdown: bool = False) -> list[str]:
    """A table as aligned columns, or as a Markdown table."""
    if markdown:
        return [
            f"| {' | '.join(map(str, row))} |" for row in [headers, ["---"] * len(headers), *rows]
        ]
    widths = [max(len(str(cell)) for cell in column) for column in zip(headers, *rows, strict=True)]
    return [
        "  ".join(str(cell).ljust(width) for cell, width in zip(row, widths, strict=True)).rstrip()
        for row in [headers, *rows]
    ]
