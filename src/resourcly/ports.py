from collections.abc import Callable
from typing import Any, Literal, Protocol

from resourcly.models import GoldDocument, ReadProgress, TraceEvent

Source = Literal["drawings", "partial"]
Splits = dict[str, dict[str, list[str]]]
Progress = Callable[[ReadProgress], None]


class GoldStorePort(Protocol):
    def list_drawings(self) -> dict[str, Source]: ...

    def exists(self, drawing: str) -> bool: ...

    def load(self, drawing: str) -> dict[str, Any]: ...

    def save(self, drawing: str, document: GoldDocument) -> None: ...

    def load_splits(self) -> Splits:
        """Case ids per split per component, such as {"reader": {"dev": [...], "test": [...]}}."""
        ...


class DrawingPagePort(Protocol):
    def list_drawings(self) -> list[str]: ...

    def page_count(self, drawing: str) -> int: ...

    def render(self, drawing: str, page: int, dpi: int) -> bytes: ...


class TracePort(Protocol):
    def record(self, event: TraceEvent) -> None: ...

    def find(self, request_id: str) -> list[TraceEvent]: ...


class ReaderPort(Protocol):
    def read(self, drawing: str, progress: Progress | None = None) -> dict[str, Any]:
        """The drawing's values as a document in the gold schema's shape, possibly invalid.

        A reader that works in steps calls `progress` before each one.
        """
        ...
