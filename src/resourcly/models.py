import mimetypes
import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Annotated, Any, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    StrictFloat,
    StrictInt,
    TypeAdapter,
    ValidationError,
    WithJsonSchema,
    computed_field,
    model_serializer,
    model_validator,
)

Number = StrictInt | StrictFloat
# Pydantic writes a bound on a union as keys JSON Schema does not know, so the schema is given
Fraction = Annotated[
    Number, Field(ge=0, le=1), WithJsonSchema({"type": "number", "minimum": 0, "maximum": 1})
]

FeatureType = Literal[
    "hole",
    "cylinder",
    "plane",
    "slot",
    "boss",
    "thread",
    "chamfer",
    "fillet",
    "edge",
    "pattern",
    "other",
]
Callout = Literal[
    "dimension",
    "feature_control_frame",
    "datum_feature_symbol",
    "datum_target",
    "note",
    "title_block",
    "surface_texture",
    "thread",
]
Characteristic = Literal[
    "straightness",
    "flatness",
    "circularity",
    "cylindricity",
    "profile_of_a_line",
    "profile_of_a_surface",
    "angularity",
    "perpendicularity",
    "parallelism",
    "position",
    "concentricity",
    "symmetry",
    "circular_runout",
    "total_runout",
]
DimensionKind = Literal["diameter", "radius", "linear", "angular"]
ToleranceStyle = Literal[
    "limits",
    "plus_minus",
    "unilateral",
    "bilateral_unequal",
    "basic",
    "reference",
    "geometric_zone",
    "none",
]
Unit = Literal["mm", "in", "deg"]
CONFIDENCE = (
    "How sure the labeller is. Gold needs it; a reading sets null, as no reader measures it"
)
Status = Literal["draft", "approved"]

KINDS_BY_CALLOUT: dict[str, tuple[str, ...]] = {
    "feature_control_frame": Characteristic.__args__,
    "dimension": DimensionKind.__args__,
    "datum_feature_symbol": ("datum_feature",),
    "datum_target": ("datum_target",),
    "note": ("note",),
    "title_block": ("title_block",),
    "surface_texture": ("surface_texture",),
    "thread": ("thread",),
}


class Issue(BaseModel):
    loc: list[str | int]
    message: str


class RecordError(ValueError):
    def __init__(self, issues: list[Issue]):
        self.issues = issues
        super().__init__("; ".join(issue.message for issue in issues))


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TitleBlock(Record):
    title: str | None = None
    revision: str | None = None
    units: Literal["mm", "in"] | None = None
    units_source: Literal["stated", "inferred"] | None = None
    drawing_number: str | None = None
    sheet_note: str | None = None
    standard: str | None = None


class Feature(Record):
    id: str = Field(
        pattern=r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$", description="snake_case, unique in the drawing."
    )
    type: FeatureType
    label: str = Field(min_length=1)
    description: str
    page: int = Field(ge=1)


class Limits(Record):
    lower: Number
    upper: Number

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.lower > self.upper:
            raise ValueError("lower must not exceed upper")
        return self


class Value(Record):
    id: str = Field(
        pattern=r"^[a-z0-9]+-\d{2,}$", description="<drawing short>-<nn>, e.g. ctc01-15"
    )
    raw: str = Field(
        min_length=1,
        description="Exactly as printed, with unicode GD&T symbols and | between frame cells.",
    )
    callout: Callout
    kind: str
    tolerance_style: ToleranceStyle
    value: Number | tuple[Number, Number] | None = Field(
        description="A number, [lower, upper] for a limit dimension, or null with no number."
    )
    unit: Unit | None
    feature_id: str | None = Field(
        description="Points into features; null only for title_block values."
    )
    applies_to: str | None = None
    datums: list[Annotated[str, Field(min_length=1)]] = []
    limits: Limits | None
    meaning: str
    page: int = Field(ge=1)
    bbox: tuple[Fraction, Fraction, Fraction, Fraction] = Field(
        description="[x0, y0, x1, y1] as fractions of the rendered page width and height."
    )
    # How sure the labeller is. Gold needs it; a reader leaves it None, as no reader measures it.
    confidence: Fraction | None = Field(description=CONFIDENCE)
    status: Status = "draft"

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        issues = []
        allowed = KINDS_BY_CALLOUT[self.callout]
        if self.kind not in allowed:
            issues.append(
                Issue(
                    loc=["kind"],
                    message=f"'{self.kind}' is not a {self.callout} "
                    f"kind; use one of: {', '.join(allowed)}",
                )
            )
        x0, y0, x1, y1 = self.bbox
        if x0 >= x1 or y0 >= y1:
            issues.append(
                Issue(loc=["bbox"], message="must be [x0, y0, x1, y1] with x0 < x1 and y0 < y1")
            )
        if isinstance(self.value, tuple) and self.value[0] > self.value[1]:
            issues.append(Issue(loc=["value"], message="a range must be [lower, upper]"))
        if self.tolerance_style == "limits" and not isinstance(self.value, tuple):
            issues.append(Issue(loc=["value"], message="a limit dimension stores [lower, upper]"))
        if self.tolerance_style == "geometric_zone" and self.limits and self.limits.lower != 0:
            issues.append(Issue(loc=["limits"], message="lower must be 0 for a geometric zone"))
        if self.kind == "angular" and self.unit not in ("deg", None):
            issues.append(Issue(loc=["unit"], message="an angle is measured in deg"))
        if self.unit == "deg" and self.kind != "angular":
            issues.append(Issue(loc=["unit"], message="deg is only for angular dimensions"))
        if issues:
            raise RecordError(issues)
        return self


class GoldDocument(Record):
    """Every value on one drawing, its feature and what it means, in ASME Y14.5 terms."""

    model_config = ConfigDict(title="Drawing gold document")

    drawing: str = Field(min_length=1, description="PDF file stem, e.g. nist_ctc_01_asme1_rd.")
    page_count: int = Field(ge=1)
    # Left out of the dump when None.
    page_coverage: list[Annotated[int, Field(ge=1)]] | None = Field(
        default=None,
        min_length=1,
        description="The pages labelled in full, in ascending order; absent means every page.",
    )
    title_block: TitleBlock = TitleBlock()
    features: list[Feature] = []
    values: list[Value] = []

    @model_serializer(mode="wrap")
    def _omit_absent_coverage(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        data = handler(self)
        if self.page_coverage is None:
            data.pop("page_coverage", None)
        return data

    @model_validator(mode="after")
    def _references(self) -> Self:
        issues = [
            *_duplicates("features", [f.id for f in self.features]),
            *_duplicates("values", [v.id for v in self.values]),
        ]
        coverage = self.page_coverage
        if coverage is not None:
            issues += [
                Issue(
                    loc=["page_coverage"],
                    message=f"page {page} is beyond page_count {self.page_count}",
                )
                for page in coverage
                if page > self.page_count
            ]
            if coverage != sorted(set(coverage)):
                issues.append(
                    Issue(
                        loc=["page_coverage"],
                        message="must list pages in ascending order, each once",
                    )
                )
        feature_ids = {f.id for f in self.features}
        for section, records in (("features", self.features), ("values", self.values)):
            for index, record in enumerate(records):
                if record.page > self.page_count:
                    issues.append(
                        Issue(
                            loc=[section, index, "page"],
                            message=f"page {record.page} is beyond page_count {self.page_count}",
                        )
                    )
        prefix = drawing_short(self.drawing) or (
            self.values[0].id.split("-")[0] if self.values else ""
        )
        for index, value in enumerate(self.values):
            if not value.id.startswith(f"{prefix}-"):
                issues.append(
                    Issue(
                        loc=["values", index, "id"],
                        message=f"must start with '{prefix}-' for this drawing",
                    )
                )
            if coverage is not None and value.page not in coverage:
                issues.append(
                    Issue(
                        loc=["values", index, "page"],
                        message=f"page {value.page} is outside page_coverage {coverage}",
                    )
                )
            if value.feature_id is not None and value.feature_id not in feature_ids:
                issues.append(
                    Issue(
                        loc=["values", index, "feature_id"],
                        message=f"'{value.feature_id}' is not in features",
                    )
                )
        if issues:
            raise RecordError(issues)
        return self


def gold_json_schema() -> dict[str, Any]:
    """The JSON Schema of a gold file, generated from the models; evals/gold/schema.json holds it.

    Gold needs the confidence a reading may leave null (see validate_document), so the schema
    makes it a number.
    """
    schema = GoldDocument.model_json_schema()
    confidence = TypeAdapter(Fraction).json_schema() | {"description": CONFIDENCE}
    schema["$defs"]["Value"]["properties"]["confidence"] = confidence
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", **schema}


def drawing_short(drawing: str) -> str | None:
    match = re.match(r"nist_([a-z]+)_(\d+)_", drawing)
    return f"{match[1]}{match[2]}" if match else None


def undefined_datums(document: GoldDocument) -> list[Issue]:
    """Datums a frame names but no datum feature symbol or datum target defines."""
    defined: set[str] = set()
    for value in document.values:
        if value.callout == "datum_feature_symbol":
            defined |= _datum_letters(value.raw)
        elif value.callout == "datum_target":
            defined |= set(re.findall(r"([A-Z]+)\d+", value.raw))
    issues = []
    for index, value in enumerate(document.values):
        missing = sorted(set().union(*map(_datum_letters, value.datums)) - defined)
        if missing:
            issues.append(
                Issue(
                    loc=["values", index, "datums"],
                    message=f"no datum feature symbol defines {', '.join(missing)}",
                )
            )
    return issues


def _datum_letters(text: str) -> set[str]:
    return set(re.findall(r"[A-Z]+", re.sub(r"\(.*?\)", "", text)))


def _duplicates(section: str, ids: list[str]) -> list[Issue]:
    seen: set[str] = set()
    issues = []
    for index, item in enumerate(ids):
        if item in seen:
            issues.append(Issue(loc=[section, index, "id"], message=f"duplicate id '{item}'"))
        seen.add(item)
    return issues


def validate_document(raw: object, *, gold: bool = True) -> tuple[GoldDocument | None, list[Issue]]:
    """A gold document, or with gold=False a reader's output, which may leave confidence None."""
    try:
        document = GoldDocument.model_validate(raw)
    except ValidationError as error:
        return None, _issues(error)
    missing = [
        Issue(loc=["values", index, "confidence"], message="gold needs a confidence from 0 to 1")
        for index, value in enumerate(document.values)
        if gold and value.confidence is None
    ]
    return (None, missing) if missing else (document, [])


def _issues(error: ValidationError) -> list[Issue]:
    issues: dict[tuple, Issue] = {}
    for detail in error.errors():
        base = _field_loc(list(detail["loc"]))
        cause = detail.get("ctx", {}).get("error")
        found = (
            cause.issues
            if isinstance(cause, RecordError)
            else [Issue(loc=[], message=_message(detail))]
        )
        for issue in found:
            loc = base + issue.loc
            issues.setdefault(tuple(loc), Issue(loc=loc, message=issue.message))
    return list(issues.values())


PATTERN_HINTS = {
    "features": "use snake_case, such as boss_front",
    "values": "use <drawing short>-<nn>, such as ctc01-07",
}


def _message(detail: dict) -> str:
    ctx = detail.get("ctx", {})
    if detail["loc"][:1] == ("values",) and detail["loc"][2:3] == ("value",):
        return "must be a number, [lower, upper] or null"
    match detail["type"]:
        case "less_than_equal":
            return f"must be at most {ctx['le']}"
        case "greater_than_equal":
            return f"must be at least {ctx['ge']}"
        case "string_too_short":
            return "must not be empty"
        case "missing":
            return "is required"
        case "extra_forbidden":
            return "is not a field in the schema"
        case "string_pattern_mismatch":
            return PATTERN_HINTS.get(str(detail["loc"][0]), detail["msg"])
    return detail["msg"].replace("Input should be", "must be")


def _field_loc(loc: list[str | int]) -> list[str | int]:
    depth = 3 if loc and loc[0] in ("features", "values") else 2
    return loc[:depth]


class ReadProgress(BaseModel):
    """How far a read has got, sent before each step so a person can watch a slow read.

    `done` of `total` steps are finished over the whole drawing: callouts for a reader that reads
    them one at a time, pages for one that reads whole pages. `boxes` are the callouts found on
    `page`, as page fractions, and the first `page_done` of them are read. `latest` is the text the
    step before this one read, so a person sees what the reader finds as it goes.
    """

    page: int
    pages: int
    done: int
    total: int
    boxes: list[tuple[float, float, float, float]] = []
    page_done: int = 0
    latest: list[str] = []


class ReaderOutput(BaseModel):
    """What a reader returns: the document, and each model answer it could not use, and why."""

    document: dict[str, Any]
    answer_issues: list[Issue] = []


class Reading(BaseModel):
    request_id: str
    drawing: str
    document: dict[str, Any]
    issues: list[Issue]


class TraceEvent(BaseModel):
    """One step of a request: what the service did, what it called, with what, and the outcome."""

    request_id: str
    step: str
    called: str
    input: dict[str, Any]
    output: dict[str, Any]
    error: str | None
    started_at: str
    duration_ms: float


class RequestTrace(BaseModel):
    request_id: str
    events: list[TraceEvent]


class DrawingSummary(BaseModel):
    drawing: str
    page_count: int
    has_gold: bool
    source: Literal["drawings", "partial"] | None
    values: int
    approved: int
    issues: int


class Route(StrEnum):
    """The case a request goes to. The router picks it; the user never says."""

    DRAWING = "drawing"
    PHOTO = "photo"
    TEXT = "text"
    # an attachment that fits no case, such as a whole report or a logo
    OTHER = "other"


@dataclass(frozen=True)
class Attachment:
    name: str
    media_type: str
    data: bytes = field(repr=False)


@dataclass(frozen=True)
class LayerVerdict:
    """What one router layer made of a request: a route, or None to pass it to the next layer.

    The reason says why either way, and the confidence is 1 for a rule.
    """

    route: Route | None
    reason: str
    confidence: float | None = None
    probabilities: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class Choice:
    """A model's answer to a multiple-choice question, read from its first answer token.

    The probabilities are normalised over the options; mass is the share of the first token's
    probability that fell on the options at all, so a low mass means the model wanted to say
    something else.
    """

    probabilities: dict[str, float]
    mass: float


class Routing(BaseModel):
    """The router's answer to one request: the route, the layer that decided it, and why."""

    request_id: str
    route: Route
    layer: str
    confidence: float | None
    reason: str
    probabilities: dict[str, float]
    elapsed_ms: float


class FigureMatch(BaseModel):
    """A report figure that shows the failure in a photo, with what the report says it shows."""

    figure: str  # <report>/fig<nn>, such as 18-061/fig06
    report: str
    section: str
    failure_mode: str
    score: float | None = None  # how close the finder found it, when it measures that


class Passage(BaseModel):
    """A paragraph of a report, cited by its report and the page it starts on."""

    report: str
    page: int
    text: str

    @property
    def source(self) -> str:
        """How an answer cites it, such as 18-061 p3."""
        return f"{self.report} p{self.page}"


class FigureEvidence(BaseModel):
    """What a report says about one of its figures, for an answer to cite."""

    figure: str  # <report>/fig<nn>, such as 18-061/fig05
    report: str
    page: int
    section: str
    failure_mode: str
    caption: str
    citing: list[Passage]  # the paragraphs that name the figure

    @property
    def source(self) -> str:
        """How an answer cites it, such as 18-061 fig05."""
        return self.figure.replace("/", " ")


class ReportEvidence(BaseModel):
    """What a report is about, and its closing paragraphs, for an answer to cite."""

    report: str
    file: str  # the PDF in the reports folder
    vehicle: str | None
    components: str | None
    closing: list[Passage]


class Citation(BaseModel):
    """A source an answer cites: a report figure, such as 18-061 fig05, or a page, 18-061 p3."""

    source: str  # as the answer cites it
    report: str
    page: int
    # <report>/fig<nn> for a figure, whose image is GET /api/reports/<report>/figures/<nn>.png
    figure: str | None = None


class Finding(BaseModel):
    """A fact from the reports that explains what is wrong, with the source it comes from."""

    statement: str
    citation: Citation


class Action(BaseModel):
    """What to do: stated in the cited report text, or inferred from the findings."""

    action: str
    basis: Literal["stated", "inferred"]
    citation: Citation | None = None


class PhotoAnswer(BaseModel):
    """What the agent says about a photo of a part, from the NTSB reports.

    `not_in_reports` is the gate: no report figure is close enough to the photo, so nothing is
    said about it. Otherwise `figures` are the closest report figures, best first, and `matched`
    says whether the model found that they show the same failure. Only the findings and actions
    whose citations are in the evidence the model was given are kept.
    """

    not_in_reports: bool
    matched: bool
    answer: str
    findings: list[Finding]
    actions: list[Action]
    figures: list[FigureMatch] = []


@dataclass(frozen=True)
class PhotoEvidence:
    """What an answerer is shown about a photo: the closest figures and their reports' text.

    `images` are the first figures as PNGs, in order; the rest are shown as text only.
    """

    question: str
    photo: bytes  # PNG
    figures: list[FigureEvidence]
    images: list[bytes]
    reports: list[ReportEvidence]


@dataclass(frozen=True)
class AnswerDraft:
    """An answerer's answer as it gave it, before its citations are checked.

    Each source is as written, such as "18-061 fig05" or "[18-061 p3]"; `text` is the whole
    answer, for the trace.
    """

    matched: bool
    answer: str
    findings: list[tuple[str, str]]  # statement, source
    actions: list[tuple[str, str, str | None]]  # action, basis, source
    text: str


class FailureMatches(BaseModel):
    """The figures a finder matched to one photo, best first; none when no report shows it."""

    request_id: str
    figures: list[FigureMatch]
    elapsed_ms: float


MAGIC_BYTES = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF8", "image/gif"),
    (b"II*\x00", "image/tiff"),
    (b"MM\x00*", "image/tiff"),
)


def guess_media_type(name: str, data: bytes) -> str:
    """The media type of a file from its first bytes, else from its name."""
    head = data[:1024]
    if b"%PDF-" in head:
        return "application/pdf"
    for magic, media_type in MAGIC_BYTES:
        if head.startswith(magic):
            return media_type
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return mimetypes.guess_type(name)[0] or "application/octet-stream"


class StoredFile(BaseModel):
    """An uploaded file as the upload store keeps it; `item_id` is unique within the request."""

    item_id: str
    name: str
    media_type: str
    size: int
    pages: int


ItemStatus = Literal["routing", "queued", "reading", "answering", "done", "failed", "answered"]
ACTIVE: tuple[ItemStatus, ...] = ("routing", "queued", "reading", "answering")


class RequestItem(BaseModel):
    """One file of a chat request, or its text when it has no file, and what the agent did.

    An item is routed, then a drawing is queued and read, and a photo is queued and answered
    from the reports; the other cases are answered at once. `values` counts the read document's
    values, and `issues` its schema issues and the model answers the reader could not use.
    `answer` is a photo's answer, and `reply` its text.
    """

    item_id: str
    kind: Literal["file", "text"]
    name: str
    media_type: str | None = None
    size: int = 0
    pages: int = 0
    route: Routing | None = None
    status: ItemStatus = "routing"
    progress: ReadProgress | None = None
    reply: str | None = None
    answer: PhotoAnswer | None = None
    values: int | None = None
    issues: int | None = None
    error: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


class RequestRecord(BaseModel):
    """One chat message: its text, its items, and when it was sent."""

    request_id: str
    text: str
    created_at: str
    items: list[RequestItem]

    @computed_field
    @property
    def status(self) -> Literal["working", "failed", "done"]:
        if any(item.status in ACTIVE for item in self.items):
            return "working"
        return "failed" if any(item.status == "failed" for item in self.items) else "done"
