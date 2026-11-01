import json
from pathlib import Path

import pytest

from resourcly.adapters.gold_store import JsonGoldStoreAdapter
from resourcly.errors import InvalidDocument, NotFound
from resourcly.models import GoldDocument
from tests.conftest import CTC01


def test_round_trip_keeps_the_document_unchanged(gold_dir: Path, ctc01: dict) -> None:
    store = JsonGoldStoreAdapter(gold_dir, gold_dir / "splits.toml")
    path = gold_dir / "drawings" / f"{CTC01}.json"
    before = path.read_text(encoding="utf-8")

    store.save(CTC01, GoldDocument.model_validate(store.load(CTC01)))

    assert path.read_text(encoding="utf-8") == before
    assert store.load(CTC01) == ctc01


def test_partial_gold_is_listed_and_saved_in_place(gold_dir: Path, ctc01: dict) -> None:
    partial = gold_dir / "partial" / "partial_a.json"
    partial.parent.mkdir()
    partial.write_text(json.dumps({**ctc01, "drawing": "partial_a"}), encoding="utf-8")
    store = JsonGoldStoreAdapter(gold_dir, gold_dir / "splits.toml")

    assert store.list_drawings() == {CTC01: "drawings", "partial_a": "partial"}
    store.save("partial_a", GoldDocument.model_validate(store.load("partial_a")))
    assert not (gold_dir / "drawings" / "partial_a.json").exists()
    assert json.loads(partial.read_text(encoding="utf-8"))["drawing"] == "partial_a"


def test_new_documents_go_to_drawings(tmp_path: Path) -> None:
    store = JsonGoldStoreAdapter(tmp_path / "gold", tmp_path / "splits.toml")

    store.save("fresh", GoldDocument(drawing="fresh", page_count=1))

    assert store.list_drawings() == {"fresh": "drawings"}
    assert store.load("fresh")["values"] == []


def test_missing_and_broken_files_raise_application_errors(gold_dir: Path) -> None:
    (gold_dir / "drawings" / "broken.json").write_text("{not json", encoding="utf-8")
    store = JsonGoldStoreAdapter(gold_dir, gold_dir / "splits.toml")

    with pytest.raises(NotFound):
        store.load("absent")
    with pytest.raises(InvalidDocument, match="1 validation issue"):
        store.load("broken")


def test_exists_covers_both_folders(gold_dir: Path, ctc01: dict) -> None:
    (gold_dir / "partial").mkdir()
    (gold_dir / "partial" / "partial_a.json").write_text("{}", encoding="utf-8")
    store = JsonGoldStoreAdapter(gold_dir, gold_dir / "splits.toml")

    assert store.exists(CTC01) and store.exists("partial_a")
    assert not store.exists("absent")


def test_splits_are_read_from_their_own_path(gold_dir: Path, tmp_path: Path) -> None:
    (gold_dir / "splits.toml").write_text('[reader]\ndev = ["beside-the-gold"]\n', encoding="utf-8")
    splits = tmp_path / "evals" / "splits.toml"
    splits.parent.mkdir()
    splits.write_text(f'[reader]\ndev = ["{CTC01}"]\n', encoding="utf-8")

    assert JsonGoldStoreAdapter(gold_dir, splits).load_splits() == {"reader": {"dev": [CTC01]}}
