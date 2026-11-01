from collections.abc import Callable
from typing import Any, Literal, Protocol

from resourcly.models import (
    Attachment,
    FigureMatch,
    GoldDocument,
    LayerVerdict,
    ReadProgress,
    Routing,
    TraceEvent,
)

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

    def load_route_cases(self) -> list[dict[str, Any]]:
        """Router gold rows, one per labelled item: id, label, unit, file, text, attachment..."""
        ...

    def load_failure_cases(self) -> list[dict[str, Any]]:
        """Failure gold rows, one per photo: case_id, image, kind, unit and the expected answer."""
        ...

    def file_exists(self, path: str) -> bool: ...

    def load_file(self, path: str) -> bytes:
        """A file the gold names, by its path under the gold folder; NotFound if it is absent."""
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


class RouterPort(Protocol):
    """Picks the case of a request from its attachment; the user never says which it is."""

    def route(
        self, text: str | None, attachment: Attachment | None, request_id: str | None = None
    ) -> Routing:
        """The route, the layer that decided it, its confidence and why, traced under request_id."""
        ...


class RouteLayerPort(Protocol):
    """One layer of the router, such as the structure rules, the probe or the fallback model."""

    name: str
    called: str  # what the layer runs, for the trace

    def decide(self, attachment: Attachment | None) -> LayerVerdict:
        """A verdict with a route, or with None to pass the request to the next layer."""
        ...


class FailureFinderPort(Protocol):
    """Finds the report figures that show the same failure as a photo of a part."""

    def find(self, photo: Attachment) -> list[FigureMatch]:
        """The matching figures, best first; an empty list when no report shows this failure."""
        ...
