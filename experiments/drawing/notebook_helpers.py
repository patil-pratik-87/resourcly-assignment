"""Display helpers for the drawing reader notebooks.

Every number comes from `resourcly.eval_harness`: the notebooks read runs from the run store, the
same runs `uv run evals run reader ...` stores, and `evals(...)` calls the `evals` command-line app
in this process, so a notebook cannot show a number the command line would not. The model runs
take up to 40 minutes each, so they are made from the command line (see README.md) and the
notebooks only read them back. This module finds runs, and draws tables and crops.
"""

import json
from pathlib import Path
from typing import Any

import pandas as pd
import pymupdf
from IPython.display import Image, Markdown, display
from typer.testing import CliRunner

from resourcly.adapters.callout_locator import locate
from resourcly.adapters.vlm_readers import crop_png, first_json
from resourcly.bootstrap import PROJECT_ROOT, READERS, Settings, load_version, open_services
from resourcly.eval_harness import metrics
from resourcly.eval_harness.cli import app
from resourcly.eval_harness.models import Case
from resourcly.eval_harness.store import SqliteResultStore
from resourcly.eval_harness.suites import scored_values

STORE = PROJECT_ROOT / "runs" / "evals.sqlite"
DRAWINGS = PROJECT_ROOT / "data" / "drawings"
# The drawings with full gold: CTC-01, CTC-03 and FTC-06, and FTC-07, whose gold covers page 2
FULL_GOLD = (
    "nist_ctc_01_asme1_rd",
    "nist_ctc_03_asme1_rc",
    "nist_ftc_06_asme1_rd",
    "nist_ftc_07_asme1_rd",
)


def evals(*args: str) -> str:
    """Run `uv run evals ARGS` in this process and print what it prints."""
    result = CliRunner().invoke(app, ["--store", str(STORE), *args])
    print(result.output)
    if result.exception and not isinstance(result.exception, SystemExit):
        raise result.exception
    return result.output


def stored_run(version: str, split: str = "all") -> str:
    """The latest finished run of the version, as it is now, on the whole split."""
    current = load_version(Settings(), "reader", version).hash
    with SqliteResultStore.open(STORE) as store:
        runs = [
            run
            for run in store.runs("reader")
            if run.version == version
            and run.version_hash == current
            and run.split == split
            and not run.case_ids
            and run.finished_at
        ]
    if not runs:
        raise LookupError(
            f"no finished run of {version} on the {split} split; make one with"
            f" `uv run --extra vlm evals run reader --version {version} --split {split}`"
        )
    return max(runs, key=lambda run: run.started_at).run_id


def case_table(run_id: str) -> pd.DataFrame:
    """One row per case: the harness scores, the time and the time per page."""
    with SqliteResultStore.open(STORE) as store:
        cases = store.cases(run_id)
    rows = []
    for case in cases:
        s = case.scores
        document = (case.prediction or {}).get("document") or {}
        pages = document.get("page_count") or 1
        full = case.stratum == "full"
        rows.append(
            {
                "drawing": case.case_id,
                "gold": case.stratum,
                "gold values": s["gold"],
                "predicted": s["predicted"],
                "matched": s["matched"],
                "precision": s["precision"] if full else None,
                "recall": s["recall"],
                "F1": s["f1"] if full else None,
                "pages": pages,
                "seconds": round(case.latency_ms / 1000, 1),
                "seconds per page": round(case.latency_ms / 1000 / pages, 1),
                "error": case.error,
            }
        )
    return pd.DataFrame(rows).set_index("drawing").round(3)


def run_summary(run_id: str) -> dict[str, Any]:
    """The run's summary metrics plus the time per page, for the comparison table."""
    with SqliteResultStore.open(STORE) as store:
        run = store.run(run_id)
        cases = store.cases(run_id)
    pages = sum(((c.prediction or {}).get("document") or {}).get("page_count") or 1 for c in cases)
    seconds = sum(c.latency_ms for c in cases) / 1000
    s = run.summary
    return {
        "version": run.version,
        "run": run.run_id,
        "F1": s["f1"],
        "precision": s["precision"],
        "recall": s["recall"],
        "partial recall": s["partial_recall"],
        "errors": run.errors,
        "pages": pages,
        "minutes": round(seconds / 60, 1),
        "seconds per page": round(seconds / pages, 1),
    }


def page_image(drawing: str, page: int, dpi: int = 80) -> Image:
    with pymupdf.open(DRAWINGS / f"{drawing}.pdf") as pdf:
        return Image(pdf[page - 1].get_pixmap(dpi=dpi).tobytes("png"))


def locator_overlay(drawing: str, page: int, dpi: int = 110) -> Image:
    """The page with each located callout boxed: red for frames, green for text."""
    with pymupdf.open(DRAWINGS / f"{drawing}.pdf") as pdf:
        sheet = pdf[page - 1]
        for callout in locate(sheet):
            box = callout.box
            rect = pymupdf.Rect(box.x0, box.y0, box.x1, box.y1) * sheet.derotation_matrix
            colour = (1, 0, 0) if callout.framed else (0, 0.6, 0)
            sheet.draw_rect(rect, color=colour, width=0.8)
        return Image(sheet.get_pixmap(dpi=dpi).tobytes("png"))


def region(drawing: str, page: int, bbox: list[float], dpi: int = 200, pad: float = 0.01) -> bytes:
    """The page region of a [x0, y0, x1, y1] page-fraction box, with a small margin, as PNG."""
    with pymupdf.open(DRAWINGS / f"{drawing}.pdf") as pdf:
        sheet = pdf[page - 1]
        w, h = sheet.rect.width, sheet.rect.height
        x0, y0, x1, y1 = bbox
        clip = pymupdf.Rect((x0 - pad) * w, (y0 - pad) * h, (x1 + pad) * w, (y1 + pad) * h)
        pix = sheet.get_pixmap(dpi=dpi)
        k = dpi / 72
        area = pymupdf.IRect(clip.x0 * k, clip.y0 * k, clip.x1 * k, clip.y1 * k) & pix.irect
        out = pymupdf.Pixmap(pix.colorspace, area, False)
        out.copy(pix, area)
        return out.tobytes("png")


def failures(run_id: str, case_id: str, limit: int = 12, crops: bool = True) -> None:
    """The gold records the run missed and its extra predictions, each with its page region."""
    with SqliteResultStore.open(STORE) as store:
        case = next(c for c in store.cases(run_id) if c.case_id == case_id)
    with open_services(Settings.from_env()) as services:
        gold = services.gold.load(case_id)
    scored = scored_values(Case(case_id, "", case.stratum, gold), case.prediction)
    missed, extra = metrics.unmatched(gold["values"], scored)
    heading = "extra predictions" if case.stratum == "full" else "not in the partial gold"
    display(Markdown(f"**{case_id}**: {len(missed)} missed, {len(extra)} {heading}"))
    for label, records in (("missed", missed), (heading, extra)):
        for record in records[:limit]:
            value = record.get("value")
            text = (
                f"{label}: page {record['page']} `{record['kind']}` `{record['raw']}` value {value}"
            )
            display(Markdown(text))
            whole = list(record.get("bbox") or []) == [0.0, 0.0, 1.0, 1.0]
            if crops and record.get("bbox") and not whole:
                display(Image(region(case_id, record["page"], record["bbox"])))


def missed(run_id: str, case_id: str) -> list[dict[str, Any]]:
    """The gold records of a case that the run did not match."""
    with SqliteResultStore.open(STORE) as store:
        case = next(c for c in store.cases(run_id) if c.case_id == case_id)
    with open_services(Settings.from_env()) as services:
        gold = services.gold.load(case_id)
    scored = scored_values(Case(case_id, "", case.stratum, gold), case.prediction)
    return metrics.unmatched(gold["values"], scored)[0]


def ask_crop(version: str, drawing: str, page: int, bbox: list[float]) -> None:
    """Show the located callout crop under a gold box and the model's raw answer to the prompt.

    This loads the model, so it needs `--extra vlm` and the model in the local cache.
    """
    params = load_version(Settings(), "reader", version).params
    reader = READERS["vector-crop"].build(Settings(), params)
    with pymupdf.open(DRAWINGS / f"{drawing}.pdf") as pdf:
        sheet = pdf[page - 1]
        w, h = sheet.rect.width, sheet.rect.height
        target = pymupdf.Rect(bbox[0] * w, bbox[1] * h, bbox[2] * w, bbox[3] * h)
        callouts = locate(sheet)
        pix = sheet.get_pixmap(dpi=reader.crop_dpi)
        for callout in callouts:
            box = pymupdf.Rect(callout.box.x0, callout.box.y0, callout.box.x1, callout.box.y1)
            if (box & target).is_empty:
                continue
            others = [c.box for c in callouts if c is not callout]
            image = crop_png(pix, callout.box, others, reader.crop_dpi, reader.margin)
            answer = reader.model.generate(reader.prompt, [image], reader.max_tokens)
            display(Image(image, width=320))
            print(
                json.dumps(first_json(answer), ensure_ascii=False) if first_json(answer) else answer
            )


def write_outputs(run_id: str, folder: Path) -> list[Path]:
    """Write each case's predicted document of a run as <drawing>.json in the folder."""
    folder.mkdir(parents=True, exist_ok=True)
    written = []
    with SqliteResultStore.open(STORE) as store:
        for case in store.cases(run_id):
            document = (case.prediction or {}).get("document")
            if document:
                path = folder / f"{case.case_id}.json"
                path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n")
                written.append(path)
    return written
