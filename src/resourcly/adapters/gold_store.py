import json
import tomllib
from pathlib import Path
from typing import Any

from resourcly.errors import InvalidDocument, NotFound
from resourcly.models import GoldDocument, Issue
from resourcly.ports import Source, Splits

SOURCES: tuple[Source, ...] = ("drawings", "partial")


class JsonGoldStoreAdapter:
    """One JSON document per drawing under <root>/drawings and <root>/partial.

    The splits file sits apart from the gold, at `splits_path`.
    """

    def __init__(self, root: Path, splits_path: Path):
        self.root = root
        self.splits_path = splits_path

    def list_drawings(self) -> dict[str, Source]:
        found: dict[str, Source] = {}
        for source in reversed(SOURCES):
            for path in sorted((self.root / source).glob("*.json")):
                found[path.stem] = source
        return dict(sorted(found.items()))

    def exists(self, drawing: str) -> bool:
        return self._existing(drawing) is not None

    def load(self, drawing: str) -> dict[str, Any]:
        path = self._existing(drawing)
        if path is None:
            raise NotFound(f"no gold document for {drawing}")
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            issue = Issue(loc=[], message=f"{path.name} is not valid JSON: {error}")
            raise InvalidDocument([issue]) from error

    def save(self, drawing: str, document: GoldDocument) -> None:
        path = self._existing(drawing) or self.root / "drawings" / f"{drawing}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(document.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n"
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(path)

    def load_splits(self) -> Splits:
        path = self.splits_path
        if not path.is_file():
            return {}
        try:
            return tomllib.loads(path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as error:
            issue = Issue(loc=[], message=f"{path.name} is not valid TOML: {error}")
            raise InvalidDocument([issue]) from error

    def _existing(self, drawing: str) -> Path | None:
        for source in SOURCES:
            path = self.root / source / f"{drawing}.json"
            if path.is_file():
                return path
        return None
