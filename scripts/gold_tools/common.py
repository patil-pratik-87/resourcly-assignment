"""Paths and loaders shared by the gold tools."""

import json
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[2]
DRAWINGS = ROOT / "data" / "drawings"
GOLD = ROOT / "evals" / "gold"
OUT = ROOT / "out" / "gold_tools"


def open_drawing(stem):
    path = DRAWINGS / f"{stem}.pdf"
    if not path.exists():
        raise SystemExit(f"no drawing {path.relative_to(ROOT)}")
    return pymupdf.open(path)


def load_gold(stem):
    for folder in ("drawings", "partial"):
        path = GOLD / folder / f"{stem}.json"
        if path.exists():
            return json.loads(path.read_text())
    raise SystemExit(f"no gold file for {stem} under evals/gold/drawings or evals/gold/partial")


def out_dir(path):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    return path
