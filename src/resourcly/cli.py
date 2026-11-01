from dataclasses import replace
from pathlib import Path

import typer
import uvicorn

from resourcly.api import create_app
from resourcly.bootstrap import Settings

app = typer.Typer(help="Resourcly case study server.", no_args_is_help=True)

GoldDir = typer.Option(None, "--gold-dir", help="Folder holding drawings/ and partial/.")


@app.callback()
def main() -> None:
    """Keeps `ui` a subcommand, as Typer makes a lone command the whole app."""


@app.command()
def ui(host: str = "127.0.0.1", port: int = 8000, gold_dir: Path | None = GoldDir) -> None:
    """Serve the gold label screen and its API."""
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
