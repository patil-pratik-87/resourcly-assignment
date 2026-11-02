import json
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Annotated

import typer
import uvicorn

from resourcly.api import create_app
from resourcly.bootstrap import Services, Settings, open_services
from resourcly.errors import EmptyRequest, NotFound
from resourcly.models import RequestRecord, RequestTrace

app = typer.Typer(
    help="Resourcly case study: the chat agent and its servers.", no_args_is_help=True
)

GoldDir = typer.Option(None, "--gold-dir", help="Folder holding drawings/ and partial/.")
Out = Annotated[
    Path | None, typer.Option(help="Write the JSON of each drawing read to this folder.")
]


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    """Serve the API: the chat requests, their traces and the gold endpoints."""
    settings = Settings.from_env()
    typer.echo(
        f"Chat API on http://{host}:{port}/api/requests"
        f" (reader {settings.versions['reader']}, router {settings.versions['router']})"
    )
    uvicorn.run(create_app(settings), host=host, port=port)


@app.command("annotation-ui")
def annotation_ui(
    host: str = "127.0.0.1", port: int = 8000, gold_dir: Path | None = GoldDir
) -> None:
    """Serve the gold label screen and the API."""
    settings = Settings.from_env()
    if gold_dir is not None:
        settings = replace(settings, gold_dir=gold_dir)
    if not settings.ui_dist.is_dir():
        typer.echo(
            f"No built UI at {settings.ui_dist}; serving the API only. "
            "Run `npm run build` in src/frontend/annotation first.",
            err=True,
        )
    typer.echo(f"Label screen on http://{host}:{port} (gold files in {settings.gold_dir})")
    uvicorn.run(create_app(settings), host=host, port=port)


@app.command()
def ask(
    text: Annotated[str, typer.Argument(help="The message; may be left out with --file.")] = "",
    file: Annotated[
        list[Path] | None,
        typer.Option(
            "--file",
            "-f",
            exists=True,
            help="A drawing, a picture, or a folder of them for a bulk upload. Repeat for more.",
        ),
    ] = None,
    out: Out = None,
) -> None:
    """Send one message to the agent, wait for every item, and print what it did.

    Exits with 1 when an item failed.
    """
    files = [(path.name, path.read_bytes()) for path in _expand(file or [])]
    with _short_errors(), open_services(Settings.from_env()) as services:
        record = services.agent.submit(text, files)
        typer.echo(f"request {record.request_id}: {len(record.items)} item(s), working", err=True)
        while record.status == "working":
            time.sleep(0.2)
            record = services.agent.load(record.request_id)
        _show(record)
        _save(services, record, out)
    raise typer.Exit(1 if record.status == "failed" else 0)


@app.command()
def request(
    request_id: Annotated[str, typer.Argument(help="An id from `resourcly requests`.")],
    out: Out = None,
) -> None:
    """Look up one request: what each item became, and every step it took and called.

    A request the agent did not take, such as an eval case `<run id>:<case id>`, has only steps.
    """
    with _short_errors(), open_services(Settings.from_env()) as services:
        try:
            record = services.agent.load(request_id)
        except NotFound:
            record = None
        trace = services.traces.lookup(request_id)
        if record is not None:
            _show(record)
        _show_trace(trace)
        if record is not None:
            _save(services, record, out)


@app.command()
def requests(limit: Annotated[int, typer.Option(min=1)] = 20) -> None:
    """The latest requests, newest first."""
    with open_services(Settings.from_env()) as services:
        records = services.agent.list(limit)
    for record in records:
        line = f"{record.request_id}  {record.status}  {len(record.items)} item(s)"
        line += f"  {record.created_at}"
        typer.echo(f'{line}  "{_shorten(record.text)}"' if record.text else line)


def _expand(paths: list[Path]) -> list[Path]:
    """The files given, with a folder replaced by the files in it, hidden ones left out."""
    found = []
    for path in paths:
        if path.is_dir():
            found += [
                child
                for child in sorted(path.iterdir())
                if child.is_file() and not child.name.startswith(".")
            ]
        else:
            found.append(path)
    return found


def _show(record: RequestRecord) -> None:
    typer.echo(f"request {record.request_id}  {record.status}  {record.created_at}")
    if record.text:
        typer.echo(f'  text: "{_shorten(record.text)}"')
    for item in record.items:
        route = item.route
        case = f"{route.route.value} ({route.layer}, {route.confidence}), " if route else ""
        # A file renamed on upload, or rejected, is named as sent too.
        renamed = item.kind == "file" and Path(item.name).stem != item.item_id
        label = f"{item.item_id} ({item.name})" if renamed else item.item_id
        typer.echo(f"  {label}: {case}{item.status}")
        if item.values is not None:
            typer.echo(f"    {item.values} values, {item.issues} schema issues")
        if item.reply:
            typer.echo(f"    {item.reply}")
        if item.error:
            typer.echo(f"    error: {item.error}")


def _show_trace(trace: RequestTrace) -> None:
    typer.echo(f"trace: {len(trace.events)} step(s)")
    for event in trace.events:
        typer.echo(
            f"  {event.started_at}  {event.step}  called {event.called}  {event.duration_ms} ms"
        )
        typer.echo(f"    input   {json.dumps(event.input, ensure_ascii=False)}")
        typer.echo(f"    output  {json.dumps(event.output, ensure_ascii=False)}")
        if event.error:
            typer.echo(f"    error   {event.error}")


def _save(services: Services, record: RequestRecord, out: Path | None) -> None:
    if out is None:
        return
    out.mkdir(parents=True, exist_ok=True)
    for item in record.items:
        if item.status == "done":
            document = services.agent.result(record.request_id, item.item_id)
            path = out / f"{item.item_id}.json"
            path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
            typer.echo(f"wrote {path}")


@contextmanager
def _short_errors() -> Iterator[None]:
    """A refused message or an unknown request as one line, not a traceback."""
    try:
        yield
    except (EmptyRequest, NotFound) as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(1) from error


def _shorten(text: str, limit: int = 60) -> str:
    line = " ".join(text.split())
    return line if len(line) <= limit else f"{line[: limit - 1]}…"
