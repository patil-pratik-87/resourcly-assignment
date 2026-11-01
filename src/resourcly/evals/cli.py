import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any

import typer

from resourcly.bootstrap import (
    IMPLEMENTATIONS,
    PROJECT_ROOT,
    Settings,
    list_versions,
    load_version,
    open_services,
)
from resourcly.evals import harness
from resourcly.evals.cases import Case, check_gold
from resourcly.evals.compare import compare_runs
from resourcly.evals.models import CaseResult, Run
from resourcly.evals.ports import ResultStorePort
from resourcly.evals.store import SqliteResultStore
from resourcly.evals.suites import SUITES, Suite

app = typer.Typer(help="Measure each part of the agent on its gold cases.", no_args_is_help=True)

DEFAULT_STORE = PROJECT_ROOT / "runs" / "evals.sqlite"


@dataclass(frozen=True)
class Context:
    settings: Settings
    store: Path


StorePath = Annotated[
    Path, typer.Option("--store", envvar="RESOURCLY_EVALS_DB", help="SQLite file of the results.")
]
GoldDir = Annotated[
    Path | None,
    typer.Option("--gold-dir", help="Folder holding drawings/ and partial/."),
]
SplitsPath = Annotated[
    Path | None,
    typer.Option("--splits", help="TOML file naming each component's dev and test cases."),
]
Component = Annotated[str, typer.Argument(help="reader or router")]


@app.callback()
def main(
    ctx: typer.Context,
    store: StorePath = DEFAULT_STORE,
    gold_dir: GoldDir = None,
    splits: SplitsPath = None,
) -> None:
    logging.basicConfig(format="warning: %(message)s", level=logging.WARNING, force=True)
    settings = Settings.from_env()
    if gold_dir is not None:
        settings = replace(settings, gold_dir=gold_dir)
    if splits is not None:
        settings = replace(settings, splits_path=splits)
    ctx.obj = Context(settings, store)


@app.command()
def run(
    ctx: typer.Context,
    component: Annotated[str | None, typer.Argument(help="reader or router")] = None,
    version: Annotated[str | None, typer.Option(help="A file in versions/<component>/.")] = None,
    split: Annotated[str, typer.Option(help="dev, test or all.")] = "dev",
    case_id: Annotated[
        list[str] | None, typer.Option(help="Run only these cases; every case by default.")
    ] = None,
    note: Annotated[str | None, typer.Option(help="Free text stored with the run.")] = None,
    rescore: Annotated[
        str | None,
        typer.Option(
            metavar="RUN_ID",
            help="Score this run's stored predictions against the current gold, as a new run.",
        ),
    ] = None,
) -> None:
    """Run a version of a component on the gold cases of a split, or rescore a stored run."""
    context: Context = ctx.obj
    if rescore is not None:
        if component is not None or version is not None:
            raise typer.BadParameter("--rescore takes no component or --version")
        _rescore(context, rescore)
        return
    if component is None or version is None:
        raise typer.BadParameter("give a component and --version, or --rescore RUN_ID")
    suite = _suite(component)
    progress = {"done": 0, "total": 0}

    def started(run: Run, chosen: list[Case], pool: int) -> None:
        progress["total"] = len(chosen)
        names = " ".join(case.case_id for case in chosen)
        typer.echo(f"selected {len(chosen)} of {pool} {split} cases: {names}")
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

    with SqliteResultStore.open(context.store) as store, _short_errors():
        result = harness.run(
            component,
            version,
            settings=context.settings,
            store=store,
            split=split,
            case_ids=tuple(case_id or ()),
            note=note,
            on_start=started,
            on_case=finished,
        )
    typer.echo(f"run {result.run_id}  (case set {result.case_set_hash}, store {context.store})")
    typer.echo("")
    _summary(suite.primary_metric, suite.metrics, result)


def _rescore(context: Context, run_id: str) -> None:
    with SqliteResultStore.open(context.store) as store:
        _run(store, run_id)
        with _short_errors():
            result = harness.rescore(run_id, settings=context.settings, store=store)
    typer.echo(f"run {result.run_id}  (rescore of {run_id}, case set {result.case_set_hash})")
    typer.echo("")
    suite = SUITES[result.component]
    _summary(suite.primary_metric, suite.metrics, result)


@app.command()
def compare(
    ctx: typer.Context,
    component: Component,
    base: Annotated[str, typer.Argument(help="A run id, or a version for its latest run.")],
    candidate: Annotated[str, typer.Argument(help="A run id, or a version for its latest run.")],
    fail_if_worse: Annotated[bool, typer.Option(help="Exit 1 if the primary got worse.")] = False,
) -> None:
    """Whether the candidate is better or worse than the base, metric by metric and case by case."""
    context: Context = ctx.obj
    suite = _suite(component)
    with SqliteResultStore.open(context.store) as store, _short_errors():
        runs = _pair(store, context.settings, component, base, candidate)
        comparison = compare_runs(
            runs[0],
            store.cases(runs[0].run_id),
            runs[1],
            store.cases(runs[1].run_id),
            metrics=suite.metrics,
            primary=suite.primary_metric,
            lower_is_better=suite.lower_is_better,
        )
    for label, run in (("base", runs[0]), ("candidate", runs[1])):
        typer.echo(
            f"{label.ljust(9)}  {run.run_id}  {run.version}  hash {run.version_hash}"
            f"  split {run.split}  {run.n_cases} case(s)"
        )
    typer.echo("")
    rows = [
        [
            f"{m.name} (primary)" if m.name == suite.primary_metric else m.name,
            _num(m.base),
            _num(m.candidate),
            "-" if m.delta is None else f"{m.delta:+.3f}",
            m.verdict,
        ]
        for m in comparison.metrics
    ]
    _table(["metric", "base", "candidate", "delta", "verdict"], rows)
    typer.echo("")
    typer.echo("cases by change in case_score")
    for change in sorted(comparison.cases, key=lambda c: (c.delta, c.case_id)):
        typer.echo(
            f"  {change.case_id}  {_num(change.base)} -> {_num(change.candidate)}"
            f"  {change.delta:+.3f}"
        )
    for warning in comparison.warnings:
        typer.echo(f"warning: {warning}", err=True)
    if fail_if_worse and not comparison.comparable:
        typer.echo(f"no verdict on {suite.primary_metric}", err=True)
        raise typer.Exit(1)
    if fail_if_worse and comparison.worse:
        typer.echo(f"{suite.primary_metric} got worse", err=True)
        raise typer.Exit(1)


@app.command()
def show(
    ctx: typer.Context,
    run_ids: Annotated[
        list[str] | None,
        typer.Argument(
            help="A run id from `evals list runs`; with --out, any number of them, or none for the"
            " latest full run of each version and split."
        ),
    ] = None,
    case: Annotated[str | None, typer.Option(help="Explain one case against the gold.")] = None,
    failures: Annotated[
        bool, typer.Option(help="Only cases that failed or scored below 1.")
    ] = False,
    out: Annotated[
        Path | None, typer.Option(help="Write Markdown tables of the runs to this file.")
    ] = None,
    request: Annotated[
        str | None,
        typer.Option(metavar="REQUEST_ID", help="What one request did and called, step by step."),
    ] = None,
) -> None:
    """A run's settings, summary and cases; a request's trace; or Markdown tables of runs."""
    context: Context = ctx.obj
    if request is not None:
        if run_ids or case or failures or out:
            raise typer.BadParameter("--request takes no run id or other option")
        _trace(context, request)
        return
    if out is not None:
        if case or failures:
            raise typer.BadParameter("--out takes no --case or --failures")
        _report(context, run_ids or [], out)
        return
    if not run_ids or len(run_ids) > 1:
        raise typer.BadParameter("give one run id, --request REQUEST_ID or --out FILE")
    run_id = run_ids[0]
    with SqliteResultStore.open(context.store) as store:
        run = _run(store, run_id)
        results = store.cases(run_id)
    suite = SUITES[run.component]
    if case is not None:
        _explain(context, run, suite, next((r for r in results if r.case_id == case), None), case)
        return
    typer.echo(f"run {run.run_id}  {run.component} {run.version} (hash {run.version_hash})")
    typer.echo(f"split {run.split}  selection {run.selection}  case set {run.case_set_hash}")
    finished = run.finished_at or "-"
    typer.echo(f"started {run.started_at}  finished {finished}  git {_git_label(run)}")
    for label, text in (("rescore of", run.rescored_from), ("note", run.note)):
        if text:
            typer.echo(f"{label} {text}")
    typer.echo("")
    _summary(suite.primary_metric, suite.metrics, run)
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
    typer.echo("")
    typer.echo("what a case did and called:")
    for r in shown:
        typer.echo(f"  uv run evals show --request {r.request_id}")


def _trace(context: Context, request_id: str) -> None:
    with _short_errors(), open_services(context.settings) as services:
        trace = services.traces.lookup(request_id)
    typer.echo(f"request {trace.request_id}: {len(trace.events)} step(s)")
    for event in trace.events:
        typer.echo(
            f"  {event.started_at}  {event.step}  called {event.called}  {event.duration_ms} ms"
        )
        typer.echo(f"    input   {json.dumps(event.input, ensure_ascii=False)}")
        typer.echo(f"    output  {json.dumps(event.output, ensure_ascii=False)}")
        if event.error:
            typer.echo(f"    error   {event.error}")


def _report(context: Context, run_ids: list[str], out: Path) -> None:
    """Markdown tables of runs, for results that go in the repository.

    Without run ids it takes the latest finished run of each version and split that ran every case
    of the split, so a run on a few cases never replaces the full one.
    """
    with SqliteResultStore.open(context.store) as store:
        if run_ids:
            runs = [_run(store, run_id) for run_id in run_ids]
        else:
            latest: dict[tuple[str, str, str], Run] = {}
            for run in store.runs():
                if run.finished_at and _selected(run) is None:
                    latest.setdefault((run.component, run.version, run.split), run)
            runs = [latest[key] for key in sorted(latest)]
            if not runs:
                typer.echo("error: no finished full run to write; name run ids", err=True)
                raise typer.Exit(1)
        sections = [_markdown(run, store.cases(run.run_id)) for run in runs]
    text = "# Eval results\n\nWritten by `uv run evals show --out`.\n" + "".join(sections)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    typer.echo(f"wrote {len(runs)} run(s) to {out}")


class Listing(StrEnum):
    components = "components"
    versions = "versions"
    cases = "cases"
    runs = "runs"


@app.command("list")
def list_(
    ctx: typer.Context,
    what: Annotated[Listing, typer.Argument(help="What to list.")],
    component: Annotated[
        str | None, typer.Argument(help="reader or router; cases need one.")
    ] = None,
    split: Annotated[str, typer.Option(help="dev, test or all, for cases.")] = "dev",
    version: Annotated[str | None, typer.Option(help="Only this version's runs.")] = None,
    limit: Annotated[int, typer.Option(help="How many runs.")] = 20,
) -> None:
    """Components and their implementations, version files, a component's cases, or runs."""
    context: Context = ctx.obj
    if what is Listing.components:
        _list_components(context)
    elif what is Listing.versions:
        _list_versions(context, component)
    elif what is Listing.cases:
        if component is None:
            raise typer.BadParameter("cases need a component: reader or router")
        _list_cases(context, component, split)
    else:
        _list_runs(context, component, version, limit)


def _list_components(context: Context) -> None:
    with _short_errors():
        counts = {name: len(list_versions(context.settings, name)) for name in SUITES}
    rows = [
        [
            name,
            suite.primary_metric,
            ", ".join(sorted(IMPLEMENTATIONS.get(name, {}))) or "none registered yet",
            f"{counts[name]} version(s)",
        ]
        for name, suite in SUITES.items()
    ]
    _table(["component", "primary", "implementations", "versions"], rows)


def _list_versions(context: Context, component: str | None) -> None:
    with SqliteResultStore.open(context.store) as store, _short_errors():
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
            for version in list_versions(context.settings, name)
        ]
    _table(["component", "version", "impl", "hash", "runs", "description"], rows)


def _list_cases(context: Context, component: str, split: str) -> None:
    with _short_errors(), open_services(context.settings) as services:
        cases = _suite(component).load(services, split)
    _table(
        ["case", "split", "stratum", "gold hash"],
        [[case.case_id, case.split, case.stratum, case.gold_hash] for case in cases],
    )


def _list_runs(context: Context, component: str | None, version: str | None, limit: int) -> None:
    with SqliteResultStore.open(context.store) as store:
        runs = store.runs(component, version, limit)
    rows = []
    for run in runs:
        primary = SUITES[run.component].primary_metric
        value = (run.summary or {}).get(primary)
        rows.append(
            [
                run.run_id,
                run.version,
                run.split,
                str(run.n_cases),
                str(run.errors),
                f"{primary} {_num(value)}" if run.finished_at else "unfinished",
                run.rescored_from and f"rescore of {run.rescored_from}" or "",
            ]
        )
    _table(["run", "version", "split", "cases", "errors", "primary", ""], rows)


@app.command()
def check(ctx: typer.Context) -> None:
    """Check every gold file and the splits; exit 1 on an error, warn about gaps.

    Drawing gold goes through the package models and the rules beyond them; router gold through its
    row checks; and every split for leaks and gaps.
    """
    context: Context = ctx.obj
    with _short_errors(), open_services(context.settings) as services:
        found = check_gold(services)
    for level, message in found:
        typer.echo(f"{'ok   ' if level == 'ok' else level + ':'} {message}")
    errors = sum(1 for level, _ in found if level == "error")
    warnings = sum(1 for level, _ in found if level == "warning")
    typer.echo(f"{errors} error(s), {warnings} warning(s)")
    if errors:
        raise typer.Exit(1)


@contextmanager
def _short_errors() -> Iterator[None]:
    """A missing or invalid version, case or file is the user's to fix: one line, exit 1."""
    try:
        yield
    except (LookupError, ValueError) as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(1) from error


def _pair(
    store: ResultStorePort, settings: Settings, component: str, base: str, candidate: str
) -> tuple[Run, Run]:
    """The runs two refs name. A version stands for its latest finished run, but a run on the
    same case set as the other side is preferred, so that both are scored on the same cases."""
    options = [_runs_of(store, component, ref) for ref in (base, candidate)]
    pair = next(
        (
            (old, new)
            for old in options[0]
            for new in options[1]
            if old.case_set_hash == new.case_set_hash and old.run_id != new.run_id
        ),
        (options[0][0], options[1][0]),
    )
    for ref, run in zip((base, candidate), pair, strict=True):
        if ref != run.run_id:
            _warn_if_edited(settings, component, ref, run)
    if pair[0].run_id == pair[1].run_id:
        typer.echo(
            f"warning: the base and the candidate are the same run, {pair[0].run_id}", err=True
        )
    return pair


def _runs_of(store: ResultStorePort, component: str, ref: str) -> list[Run]:
    """[the run] for a run id, or a version's finished runs, newest first."""
    try:
        runs = [store.run(ref)]
    except LookupError:
        runs = [run for run in store.runs(component, ref) if run.finished_at]
        if not runs:
            raise typer.BadParameter(
                f"'{ref}' is neither a run id nor a version with runs"
            ) from None
    if runs[0].component != component:
        raise typer.BadParameter(f"run {runs[0].run_id} is a {runs[0].component} run")
    return runs


def _warn_if_edited(settings: Settings, component: str, version: str, run: Run) -> None:
    try:
        now = load_version(settings, component, version).hash
    except (LookupError, ValueError) as error:
        typer.echo(f"warning: {version} can't be loaded now ({error})", err=True)
        return
    if now != run.version_hash:
        typer.echo(f"warning: {version} changed since run {run.run_id}", err=True)


def _explain(
    context: Context, run: Run, suite: Suite, result: CaseResult | None, case_id: str
) -> None:
    if result is None:
        raise typer.BadParameter(f"run {run.run_id} has no case '{case_id}'")
    with _short_errors(), open_services(context.settings) as services:
        current = {case.case_id: case for case in suite.load(services, "all")}
    case = current.get(case_id)
    if case is None:
        raise typer.BadParameter(f"'{case_id}' has no gold now")
    typer.echo(f"{case_id}  case_score {_num(result.scores['case_score'])}")
    typer.echo(f"request {result.request_id}  (uv run evals show --request {result.request_id})")
    if case.gold_hash != result.gold_hash:
        typer.echo("the gold changed since this run; compared with the current gold")
    if result.error:
        typer.echo(f"error {result.error}")
    for line in suite.explain(case, result.prediction):
        typer.echo(line)


def _markdown(run: Run, results: list[CaseResult]) -> str:
    suite = SUITES[run.component]
    summary = run.summary or {}
    selected = f" ({_selected(run)})" if _selected(run) else ""
    lines = [
        "",
        f"## {run.component} {run.version} on {run.split}{selected}: {run.run_id}",
        "",
        f"Version hash {run.version_hash}, case set {run.case_set_hash}, git {_git_label(run)}, "
        f"finished {run.finished_at}, {run.errors} error(s) in {run.n_cases} case(s).",
        "",
        "| metric | value |",
        "| --- | --- |",
    ]
    names = [suite.primary_metric, *(n for n in suite.metrics if n != suite.primary_metric)]
    for name in names:
        label = f"{name} (primary)" if name == suite.primary_metric else name
        lines.append(f"| {label} | {_num(summary.get(name))} |")
    columns = ["case_score", *suite.case_columns]
    lines += ["", f"| case | stratum | {' | '.join(columns)} | error |"]
    lines.append("| --- " * (len(columns) + 3) + "|")
    for result in results:
        cells = [_num(result.scores.get(column)) for column in columns]
        lines.append(
            f"| {result.case_id} | {result.stratum} | {' | '.join(cells)} | {result.error or ''} |"
        )
    for name, value in summary.items():
        rows = _confusion_rows(value)
        if rows:
            lines += ["", f"{name}:", "", "| gold | predicted | n |", "| --- | --- | --- |"]
            lines += [f"| {gold} | {predicted} | {n} |" for gold, predicted, n in rows]
    for name, listed in _listings(summary):
        lines += ["", f"{name} ({len(listed)}):", ""]
        lines += [f"- {_listed(row)}" for row in listed]
    return "\n".join(lines) + "\n"


def _selected(run: Run) -> str | None:
    """How a run picked part of its split, as the run options; None for every case."""
    selection = run.selection
    if selection.get("case_ids"):
        return f"--case-id {', '.join(selection['case_ids'])}"
    return None


def _confusion_rows(value: Any) -> list[tuple[str, str, int]]:
    """Rows of a confusion table stored as [[gold, predicted, n], ...] or {gold: {predicted: n}}."""
    if isinstance(value, dict):
        return [(g, p, n) for g, cells in value.items() for p, n in cells.items()]
    if isinstance(value, list) and all(isinstance(row, list) and len(row) == 3 for row in value):
        return [tuple(row) for row in value]
    return []


def _run(store: ResultStorePort, run_id: str) -> Run:
    try:
        return store.run(run_id)
    except LookupError as error:
        raise typer.BadParameter(str(error)) from error


def _summary(primary: str, metrics: tuple[str, ...], run: Run) -> None:
    summary = run.summary or {}
    names = [primary, *(name for name in metrics if name != primary)]
    rows = [
        [f"{name} (primary)" if name == primary else name, _num(summary.get(name))]
        for name in names
    ]
    rows += [
        [key, _num(value)]
        for key, value in summary.items()
        if key not in names and not isinstance(value, list | dict)
    ]
    rows.append(["errors", f"{run.errors} of {run.n_cases}"])
    _table(["metric", "value"], rows)
    for name, listed in _listings(summary):
        typer.echo("")
        typer.echo(f"{name} ({len(listed)})")
        for row in listed:
            typer.echo(f"  {_listed(row)}")


def _listings(summary: dict[str, Any]) -> list[tuple[str, list[dict[str, Any]]]]:
    """Summary entries that list cases, such as the router's mistakes, as (name, rows)."""
    return [
        (name, value)
        for name, value in summary.items()
        if isinstance(value, list) and value and all(isinstance(row, dict) for row in value)
    ]


def _listed(row: dict[str, Any]) -> str:
    if {"case", "expected", "got", "layer", "reason"} <= row.keys():
        return (
            f"{row['case']}  expected {row['expected']}  got {row['got']}"
            f"  by {row['layer']}: {row['reason']}"
        )
    return "  ".join(f"{key} {value}" for key, value in row.items())


def _suite(component: str) -> Suite:
    if component not in SUITES:
        raise typer.BadParameter(f"'{component}' is not a component; use {', '.join(SUITES)}")
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
    widths = [max(len(str(cell)) for cell in column) for column in zip(headers, *rows, strict=True)]
    for row in [headers, *rows]:
        typer.echo(
            "  ".join(
                str(cell).ljust(width) for cell, width in zip(row, widths, strict=True)
            ).rstrip()
        )
