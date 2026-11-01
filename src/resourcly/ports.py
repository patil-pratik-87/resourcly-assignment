from typing import Any, Literal, Protocol

from resourcly.models import GoldDocument

Source = Literal["drawings", "partial"]
Splits = dict[str, dict[str, list[str]]]


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
