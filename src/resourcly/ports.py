from collections.abc import Callable, Collection
from pathlib import Path
from typing import Any, Literal, Protocol

from resourcly.models import (
    AnswerDraft,
    Attachment,
    Choice,
    FigureEvidence,
    FigureMatch,
    GoldDocument,
    LayerVerdict,
    Passage,
    PhotoEvidence,
    ReaderOutput,
    ReadProgress,
    ReportEvidence,
    RequestRecord,
    Routing,
    SelectEvidence,
    Selection,
    StoredFile,
    TextDraft,
    TextEvidence,
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

    def load_question_cases(self) -> list[dict[str, Any]]:
        """Question gold rows: case_id, kind, unit, question and what a right answer shows."""
        ...

    def load_agent_cases(self) -> list[dict[str, Any]]:
        """Agent gold rows: the turns of one conversation and what its last turn's items get."""
        ...

    def file_exists(self, path: str) -> bool: ...

    def load_file(self, path: str) -> bytes:
        """A file the gold names, by its path under the gold folder; NotFound if it is absent."""
        ...


class DrawingPagePort(Protocol):
    def list_drawings(self) -> list[str]: ...

    def page_count(self, drawing: str) -> int: ...

    def render(
        self,
        drawing: str,
        page: int,
        dpi: int,
        clip: tuple[float, float, float, float] | None = None,
    ) -> bytes:
        """The page as a PNG, or only its `clip`: [x0, y0, x1, y1] in points from the top left."""
        ...

    def page_size(self, drawing: str, page: int) -> tuple[float, float]:
        """The page's width and height in points."""
        ...

    def close(self) -> None: ...


class TracePort(Protocol):
    def record(self, event: TraceEvent) -> None: ...

    def find(self, request_id: str) -> list[TraceEvent]: ...


class ReaderPort(Protocol):
    def read(self, drawing: str, progress: Progress | None = None) -> ReaderOutput:
        """The drawing's values as a document in the gold schema's shape, possibly invalid.

        A reader that works in steps calls `progress` before each one. A reader that asks a model
        returns each answer it could not use as an answer issue beside the document.
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


class ImageEncoderPort(Protocol):
    """A frozen image model that turns an attachment's picture into an embedding."""

    model_id: str
    revision: str  # the snapshot of the weights in use, or "not loaded"
    recipe: str  # how the vector is made from the model's output
    input_size: int  # the side of the square the model sees, in pixels

    def encode(self, attachment: Attachment) -> list[float]:
        """The embedding of the picture (an image, or page 1 of a PDF), of length 1."""
        ...


class VisionModelPort(Protocol):
    model_id: str
    revision: str  # the snapshot of the weights in use, or "not loaded"

    def generate(self, prompt: str, images: list[bytes], max_tokens: int) -> str:
        """The model's text answer to the prompt about the PNG images, decoded greedily."""
        ...

    def choose(self, prompt: str, images: list[bytes], options: list[str]) -> Choice:
        """The probability of each option as the answer's first token, normalised over them.

        Each option must be one token, such as a letter that the prompt defines.
        """
        ...


class FailureFinderPort(Protocol):
    """Finds the report figures that show the same failure as a photo of a part."""

    def find(self, photo: Attachment, exclude: Collection[str] = ()) -> list[FigureMatch]:
        """The matching figures, best first; an empty list when no report shows this failure.

        The figures in `exclude` are searched as if the reports did not hold them; the evals
        hide a test photo's own figure this way.
        """


class ReportEvidencePort(Protocol):
    """What the reports say about their figures, for an answer about a photo to cite."""

    def figure(self, figure: str) -> FigureEvidence:
        """The figure's caption, labels and citing paragraphs; NotFound for an unknown figure."""
        ...

    def figure_image(self, figure: str, max_side: int) -> bytes:
        """The figure as a PNG, at most max_side pixels on its long side."""
        ...

    def report(self, report: str) -> ReportEvidence: ...


class PhotoAnswererPort(Protocol):
    """Says what is wrong with a part in a photo and what to do, from the evidence it is shown."""

    called: str  # what it runs, for the trace

    def answer(self, evidence: PhotoEvidence) -> AnswerDraft:
        """An answer citing the evidence's figures and pages; matched is False when the figures
        do not show the photo's failure."""
        ...


class ReportSearchPort(Protocol):
    """Finds the report passages a question is about."""

    def search(self, query: str, k: int) -> list[Passage]:
        """The `k` passages that best match the query, best first; none when nothing matches."""
        ...


class QuestionAnswererPort(Protocol):
    """Answers a question from the evidence it is shown; code checks what it cites."""

    called: str  # what it runs, for the trace

    def select(self, evidence: SelectEvidence) -> Selection:
        """The values of a drawing that answer the question, and the kind of value it asks about."""
        ...

    def write(self, evidence: TextEvidence) -> TextDraft:
        """An answer from report passages, each statement citing the passage it comes from."""
        ...

    def gate(self, text: str) -> float:
        """The probability that a message sent with files asks for more than reading them."""
        ...


class UploadStorePort(Protocol):
    """The files of each chat request."""

    def save_file(self, request_id: str, name: str, content: bytes) -> StoredFile:
        """Keep an uploaded PDF or image; raises UnsupportedUpload for anything else."""
        ...

    def folder(self, request_id: str) -> Path:
        """The folder holding `<item_id>.pdf` for every file of the request, images included."""
        ...

    def original(self, request_id: str, item_id: str) -> tuple[bytes, str]:
        """The file as uploaded, and its media type."""
        ...


class RequestStorePort(Protocol):
    """The record of each chat request and the document read from each of its drawings."""

    def save(self, record: RequestRecord) -> None: ...

    def load(self, request_id: str) -> RequestRecord: ...

    def list(self, limit: int, conversation_id: str | None = None) -> list[RequestRecord]:
        """The latest requests, newest first; only those of one conversation when it is named."""
        ...

    def save_result(self, request_id: str, item_id: str, document: dict[str, Any]) -> None: ...

    def load_result(self, request_id: str, item_id: str) -> dict[str, Any]: ...

    def save_cached(self, key: str, reading: dict[str, Any]) -> None:
        """Keep a read under a key made of the file and the reader, for the next read of both."""
        ...

    def load_cached(self, key: str) -> dict[str, Any] | None:
        """The read kept under the key, or None."""
        ...


class JobsPort(Protocol):
    def submit(self, job: Callable[[], None], priority: int = 0) -> None:
        """Run the job later, in the background; a lower priority runs first."""
        ...
