import os
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path

from resourcly.adapters.gold_store import JsonGoldStoreAdapter
from resourcly.adapters.pdf_pages import PyMuPDFPageAdapter
from resourcly.services import GoldService

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    gold_dir: Path = PROJECT_ROOT / "evals" / "gold"
    splits_path: Path = PROJECT_ROOT / "evals" / "splits.toml"
    drawings_dir: Path = PROJECT_ROOT / "data" / "drawings"

    @classmethod
    def from_env(cls) -> "Settings":
        defaults = cls()
        return cls(
            gold_dir=Path(os.environ.get("RESOURCLY_GOLD_DIR", defaults.gold_dir)),
            splits_path=Path(os.environ.get("RESOURCLY_SPLITS", defaults.splits_path)),
            drawings_dir=Path(os.environ.get("RESOURCLY_DRAWINGS_DIR", defaults.drawings_dir)),
        )


class Services:
    """The services the CLI and the evals call."""

    def __init__(self, settings: Settings, stack: ExitStack):
        pages = PyMuPDFPageAdapter(settings.drawings_dir)
        stack.callback(pages.close)
        store = JsonGoldStoreAdapter(settings.gold_dir, settings.splits_path)
        self.gold = GoldService(store=store, pages=pages)


@contextmanager
def open_services(settings: Settings) -> Iterator[Services]:
    with ExitStack() as stack:
        yield Services(settings, stack)
