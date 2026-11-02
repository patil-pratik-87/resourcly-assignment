import hashlib
import json
import os
import threading
import tomllib
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field, replace
from functools import cached_property
from importlib.util import find_spec
from pathlib import Path
from typing import Any

from resourcly.adapters.captions_answer import CaptionsAnswerAdapter
from resourcly.adapters.dinov2_encoder import Dinov2EncoderAdapter
from resourcly.adapters.figure_index import FigureIndex, IndexedEvidenceAdapter
from resourcly.adapters.gold_store import JsonGoldStoreAdapter
from resourcly.adapters.mlx_vlm_model import MlxVlmModelAdapter, cached_snapshot
from resourcly.adapters.nearest_figures import NearestFiguresAdapter
from resourcly.adapters.pdf_pages import PyMuPDFPageAdapter
from resourcly.adapters.request_store import JsonRequestStoreAdapter
from resourcly.adapters.route_probe import LinearProbe, ProbeRouteAdapter
from resourcly.adapters.route_structure import StructureRouteAdapter
from resourcly.adapters.route_vlm import VlmRouteAdapter
from resourcly.adapters.shuffled_figures import ShuffledFiguresAdapter
from resourcly.adapters.sqlite_trace import SqliteTraceAdapter
from resourcly.adapters.stub_router import StubRouteAdapter
from resourcly.adapters.text_reader import PyMuPDFTextReaderAdapter
from resourcly.adapters.thread_jobs import ThreadJobsAdapter
from resourcly.adapters.upload_store import FileUploadStoreAdapter
from resourcly.adapters.vlm_answer import VlmPhotoAnswerAdapter
from resourcly.adapters.vlm_readers import VectorCropReaderAdapter, WholePageReaderAdapter
from resourcly.agent import AgentService, recover
from resourcly.answers import PhotoAnswerService
from resourcly.errors import InvalidVersion, ModelNotCached, NotFound
from resourcly.ports import ImageEncoderPort, RouteLayerPort, RouterPort
from resourcly.services import (
    DrawingService,
    FailureService,
    GoldService,
    ReportService,
    RouterService,
    TraceService,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    gold_dir: Path = PROJECT_ROOT / "evals" / "gold"
    splits_path: Path = PROJECT_ROOT / "evals" / "splits.toml"
    drawings_dir: Path = PROJECT_ROOT / "data" / "drawings"
    reports_dir: Path = PROJECT_ROOT / "data" / "reports"
    # The built screens: `resourcly serve` serves the chat, `resourcly annotation-ui` the labels
    chat_ui_dist: Path = PROJECT_ROOT / "src" / "frontend" / "chat" / "dist"
    annotation_ui_dist: Path = PROJECT_ROOT / "src" / "frontend" / "annotation" / "dist"
    versions_dir: Path = PROJECT_ROOT / "versions"
    trace_path: Path = PROJECT_ROOT / "var" / "traces.sqlite"
    uploads_dir: Path = PROJECT_ROOT / "var" / "uploads"
    # A chat message's files are read into memory whole, so each file's size is capped, and so is
    # the number of files in one message.
    max_upload_bytes: int = 50 * 1024 * 1024
    max_files: int = 50
    # The version each component runs, a file in versions_dir; the app and the evals both read it
    versions: dict[str, str] = field(
        default_factory=lambda: {
            "reader": "vector-crop-v2",
            "router": "three-layer-v1",
            "failure": "dinov2-base-v1",
            "answer": "photo-v1",
        }
    )

    @classmethod
    def from_env(cls) -> "Settings":
        defaults = cls()
        return cls(
            gold_dir=Path(os.environ.get("RESOURCLY_GOLD_DIR", defaults.gold_dir)),
            splits_path=Path(os.environ.get("RESOURCLY_SPLITS", defaults.splits_path)),
            drawings_dir=Path(os.environ.get("RESOURCLY_DRAWINGS_DIR", defaults.drawings_dir)),
            reports_dir=Path(os.environ.get("RESOURCLY_REPORTS_DIR", defaults.reports_dir)),
            chat_ui_dist=Path(os.environ.get("RESOURCLY_CHAT_UI_DIST", defaults.chat_ui_dist)),
            annotation_ui_dist=Path(
                os.environ.get("RESOURCLY_ANNOTATION_UI_DIST", defaults.annotation_ui_dist)
            ),
            versions_dir=Path(os.environ.get("RESOURCLY_VERSIONS_DIR", defaults.versions_dir)),
            trace_path=Path(os.environ.get("RESOURCLY_TRACE_DB", defaults.trace_path)),
            uploads_dir=Path(os.environ.get("RESOURCLY_UPLOADS_DIR", defaults.uploads_dir)),
            max_upload_bytes=int(
                os.environ.get("RESOURCLY_MAX_UPLOAD_BYTES", defaults.max_upload_bytes)
            ),
            max_files=int(os.environ.get("RESOURCLY_MAX_FILES", defaults.max_files)),
            versions={
                component: os.environ.get(f"RESOURCLY_{component.upper()}_VERSION", name)
                for component, name in defaults.versions.items()
            },
        )

    def with_version(self, component: str, name: str) -> "Settings":
        return replace(self, versions={**self.versions, component: name})


@dataclass(frozen=True)
class Version:
    """A named implementation of one component and its settings.

    It is read from versions/<component>/<name>.toml. A setting that names a file next to
    it, such as a router's probe weights, adds the file's SHA-256 to `files`, so the hash changes
    when the file does.
    """

    component: str
    name: str
    impl: str
    description: str
    params: dict[str, Any]
    files: dict[str, str] = field(default_factory=dict)

    @property
    def hash(self) -> str:
        config = {"component": self.component, "impl": self.impl, "params": self.params}
        if self.files:
            config["files"] = self.files
        text = json.dumps(config, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(text.encode()).hexdigest()[:12]


@dataclass(frozen=True)
class Implementation:
    """How to build one implementation of a component, and the settings a version may give it."""

    build: Callable[[Settings, dict[str, Any]], Any]
    settings: tuple[str, ...] = ()
    required: tuple[str, ...] = ()
    # settings that name a file, relative to the component's versions folder
    files: tuple[str, ...] = ()
    # raises InvalidVersion for settings the build would refuse, so a bad version fails to load
    check: Callable[[dict[str, Any]], None] | None = None


FALLBACK = (
    "or run without it: RESOURCLY_READER_VERSION=textlayer-v0, RESOURCLY_ROUTER_VERSION=stub-v0"
    " and RESOURCLY_ANSWER_VERSION=captions-v0 need no model"
)


def _local_model(model_id: str) -> Path:
    """The model's local folder, or ModelNotCached saying how to get it or run without it."""
    if find_spec("mlx_vlm") is None:
        raise ModelNotCached(
            f"{model_id} needs mlx-vlm on Apple silicon: run `uv sync --extra vlm`, {FALLBACK}"
        )
    try:
        return cached_snapshot(model_id)
    except ModelNotCached as error:
        raise ModelNotCached(
            f"{model_id} is not in the local Hugging Face cache; download it once with"
            f" `uv run hf download {model_id}`, {FALLBACK}"
        ) from error


_vision_models: dict[str, MlxVlmModelAdapter] = {}
_vision_lock = threading.Lock()


def vision_model(model_id: str) -> MlxVlmModelAdapter:
    """The one adapter of a vision-language model, shared by the reader, the router and the
    answer that name it. Building it loads nothing; the weights load on its first call."""
    with _vision_lock:
        if model_id not in _vision_models:
            _vision_models[model_id] = MlxVlmModelAdapter(model_id, locate=_local_model)
        return _vision_models[model_id]


def _with_model(reader: Callable[..., Any]) -> Callable[[Settings, dict[str, Any]], Any]:
    """A reader factory whose `model` setting names the vision-language model to run."""

    def build(settings: Settings, params: dict[str, Any]) -> Any:
        rest = {key: value for key, value in params.items() if key != "model"}
        return reader(settings.drawings_dir, vision_model(params["model"]), **rest)

    return build


READERS: dict[str, Implementation] = {
    "textlayer": Implementation(
        lambda settings, params: PyMuPDFTextReaderAdapter(settings.drawings_dir)
    ),
    "vector-crop": Implementation(
        _with_model(VectorCropReaderAdapter),
        settings=(
            "model",
            "prompt",
            "letter_prompt",
            "symbol_prompt",
            "crop_dpi",
            "margin",
            "max_tokens",
            "page_prompt",
            "page_dpi",
            "page_max_tokens",
        ),
        required=("model", "prompt"),
    ),
    "whole-page": Implementation(
        _with_model(WholePageReaderAdapter),
        settings=("model", "prompt", "dpi", "max_tokens"),
        required=("model", "prompt"),
    ),
}
# The image models a router probe or a failure finder can embed pictures with, by the name a
# version gives as `encoder`. Each takes the model id and the long side of the picture it sees,
# and may take a vector recipe and an input size.
ENCODERS: dict[str, Callable[..., ImageEncoderPort]] = {
    "dinov2": lambda model_id, max_side, **options: Dinov2EncoderAdapter(
        model_id, max_side, **options
    ),
}


def _three_layers(settings: Settings, params: dict[str, Any]) -> list[RouteLayerPort]:
    """The router of docs/routing.md: structure rules, a probe and a vision-language model."""
    structure = StructureRouteAdapter(
        **{key: params[key] for key in STRUCTURE_SETTINGS if key in params}
    )
    encoder = ENCODERS[params["encoder"]](
        params["encoder_model"], params.get("encoder_max_side", 1024)
    )
    probe = LinearProbe.load(settings.versions_dir / "router" / params["probe"])
    vlm = VlmRouteAdapter(
        vision_model(params["model"]), params["prompt"], params.get("vlm_max_side", 768)
    )
    return [structure, ProbeRouteAdapter(encoder, probe, params["threshold"]), vlm]


def _known_encoder(params: dict[str, Any]) -> None:
    if params["encoder"] not in ENCODERS:
        raise InvalidVersion(
            f"'{params['encoder']}' is not an image encoder; use {', '.join(sorted(ENCODERS))}"
        )


STRUCTURE_SETTINGS = (
    "vector_paths",
    "cad_max_picture",
    "prose_chars",
    "full_page_picture",
    "raster_picture",
    "pages",
)
ROUTERS: dict[str, Implementation] = {
    # A model-free stand-in, for tests and machines without the router's models.
    "stub": Implementation(
        lambda settings, params: [StubRouteAdapter(**params)], settings=("min_paths",)
    ),
    "three-layer": Implementation(
        _three_layers,
        settings=(
            *STRUCTURE_SETTINGS,
            "encoder",
            "encoder_model",
            "encoder_max_side",
            "probe",
            "threshold",
            "model",
            "vlm_max_side",
            "prompt",
        ),
        required=("encoder", "encoder_model", "probe", "threshold", "model", "prompt"),
        files=("probe",),
        check=_known_encoder,
    ),
}


def _nearest_figures(settings: Settings, params: dict[str, Any]) -> NearestFiguresAdapter:
    """The finder of research/failure: the report figures nearest the photo in an image model."""
    encoder = ENCODERS[params["encoder"]](
        params["encoder_model"],
        params.get("encoder_max_side", 1024),
        recipe=params["encoder_recipe"],
        input_size=params.get("encoder_input_size", 224),
    )
    index = FigureIndex.load(settings.versions_dir / "failure" / params["index"])
    return NearestFiguresAdapter(encoder, index, params["threshold"], params.get("top", 5))


FINDERS: dict[str, Implementation] = {
    # No model: a fixed random order of the report figures, the floor for the failure finders.
    "shuffled": Implementation(
        lambda settings, params: ShuffledFiguresAdapter(
            settings.reports_dir / "sections.toml", **params
        ),
        settings=("seed",),
    ),
    "nearest-figures": Implementation(
        _nearest_figures,
        settings=(
            "encoder",
            "encoder_model",
            "encoder_recipe",
            "encoder_input_size",
            "encoder_max_side",
            "index",
            "threshold",
            "top",
        ),
        required=("encoder", "encoder_model", "encoder_recipe", "index", "threshold"),
        files=("index",),
        check=_known_encoder,
    ),
}
# Every answer version names the figure index whose report text and figure images it cites, and
# may set how many of the closest figures it is shown, how many as images and at what size.
EVIDENCE_SETTINGS = ("index", "figures", "images", "figure_side")
ANSWERERS: dict[str, Implementation] = {
    # No model: the closest figures' captions, the floor for the photo answers.
    "captions": Implementation(
        lambda settings, params: CaptionsAnswerAdapter(),
        settings=EVIDENCE_SETTINGS,
        required=("index",),
        files=("index",),
    ),
    "vlm": Implementation(
        lambda settings, params: VlmPhotoAnswerAdapter(
            vision_model(params["model"]),
            params["prompt"],
            params["max_tokens"],
            params.get("photo_side", 1024),
            params.get("paragraph_chars", 700),
        ),
        settings=(
            *EVIDENCE_SETTINGS,
            "model",
            "prompt",
            "max_tokens",
            "photo_side",
            "paragraph_chars",
        ),
        required=("index", "model", "prompt", "max_tokens"),
        files=("index",),
    ),
}
IMPLEMENTATIONS: dict[str, dict[str, Implementation]] = {
    "reader": READERS,
    "router": ROUTERS,
    "failure": FINDERS,
    "answer": ANSWERERS,
}


def load_version(settings: Settings, component: str, name: str) -> Version:
    path = settings.versions_dir / component / f"{name}.toml"
    if not path.is_file():
        raise NotFound(f"no {component} version '{name}' in {settings.versions_dir / component}")
    try:
        params = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        raise InvalidVersion(f"{path.name} is not valid TOML: {error}") from error
    impl = params.pop("impl", None)
    registered = IMPLEMENTATIONS.get(component, {})
    if impl not in registered:
        names = ", ".join(sorted(registered)) or "none registered yet"
        raise InvalidVersion(f"'{impl}' is not a {component} implementation; use {names}")
    description = params.pop("description", "")
    unknown = sorted(params.keys() - set(registered[impl].settings))
    if unknown:
        takes = ", ".join(registered[impl].settings) or "none"
        raise InvalidVersion(
            f"{component} version '{name}': {impl} takes no setting {', '.join(unknown)};"
            f" its settings are {takes}"
        )
    missing = [key for key in registered[impl].required if key not in params]
    if missing:
        raise InvalidVersion(
            f"{component} version '{name}': {impl} needs the setting {', '.join(missing)}"
        )
    if registered[impl].check:
        registered[impl].check(params)
    files = {}
    for key in registered[impl].files:
        if key in params:
            file = path.parent / params[key]
            if not file.is_file():
                raise InvalidVersion(
                    f"{component} version '{name}' names the {key} file {params[key]},"
                    f" which is not in {path.parent}"
                )
            files[key] = hashlib.sha256(file.read_bytes()).hexdigest()[:12]
    return Version(component, name, impl, description, params, files)


def list_versions(settings: Settings, component: str) -> list[Version]:
    folder = settings.versions_dir / component
    return [load_version(settings, component, path.stem) for path in sorted(folder.glob("*.toml"))]


class Services:
    """The services the API, the CLI and the evals call.

    The gold service is built at once. The reader, the router, the failure finder, the trace file
    and the chat agent are built on first use, so gold work needs no version and no trace file.
    """

    def __init__(self, settings: Settings, stack: ExitStack):
        self._settings = settings
        self._stack = stack
        self._lock = threading.Lock()
        self._trace_adapter: SqliteTraceAdapter | None = None
        self._agent_lock = threading.Lock()
        self._agent: AgentService | None = None
        pages = PyMuPDFPageAdapter(settings.drawings_dir)
        stack.callback(pages.close)
        store = JsonGoldStoreAdapter(settings.gold_dir, settings.splits_path)
        self.gold = GoldService(store=store, pages=pages)

    @cached_property
    def drawings(self) -> DrawingService:
        return self._drawings_in(self._settings.drawings_dir)

    @property
    def agent(self) -> AgentService:
        """The chat agent and its background worker, built once even when threads ask at once."""
        with self._agent_lock:
            if self._agent is None:
                trace = self._trace()  # first, so it closes after the worker that writes to it
                jobs = ThreadJobsAdapter()
                self._stack.callback(jobs.close)
                self._agent = AgentService(
                    uploads=FileUploadStoreAdapter(self._settings.uploads_dir),
                    requests=self._requests,
                    router=self.router,
                    router_name=self.router_name,
                    drawings_in=self._drawings_in,
                    photos=lambda: self.photo_answers,
                    pages_in=PyMuPDFPageAdapter,
                    trace=trace,
                    jobs=jobs,
                )
            return self._agent

    def recover(self) -> None:
        """Mark the chat work a previous server left unfinished as failed."""
        recover(self._requests)

    @cached_property
    def _requests(self) -> JsonRequestStoreAdapter:
        return JsonRequestStoreAdapter(self._settings.uploads_dir)

    @property
    def reader_name(self) -> str:
        reader = load_version(self._settings, "reader", self._settings.versions["reader"])
        return f"{reader.name} ({reader.impl})"

    def _drawings_in(self, folder: Path) -> DrawingService:
        """A drawing service whose reader reads the PDFs in `folder`."""
        reader = load_version(self._settings, "reader", self._settings.versions["reader"])
        return DrawingService(
            reader=READERS[reader.impl].build(
                replace(self._settings, drawings_dir=folder), reader.params
            ),
            trace=self._trace(),
            reader_name=f"{reader.name} ({reader.impl})",
        )

    @cached_property
    def _router_version(self) -> Version:
        return load_version(self._settings, "router", self._settings.versions["router"])

    @cached_property
    def router(self) -> RouterPort:
        version = self._router_version
        return RouterService(
            layers=ROUTERS[version.impl].build(self._settings, version.params),
            trace=self._trace(),
            router_name=self.router_name,
        )

    @property
    def router_name(self) -> str:
        return f"{self._router_version.name} ({self._router_version.impl})"

    @cached_property
    def _failure_version(self) -> Version:
        return load_version(self._settings, "failure", self._settings.versions["failure"])

    @property
    def failure_name(self) -> str:
        return f"{self._failure_version.name} ({self._failure_version.impl})"

    @cached_property
    def failures(self) -> FailureService:
        finder = self._failure_version
        return FailureService(
            finder=FINDERS[finder.impl].build(self._settings, finder.params),
            trace=self._trace(),
            finder_name=self.failure_name,
        )

    @cached_property
    def _answer_version(self) -> Version:
        return load_version(self._settings, "answer", self._settings.versions["answer"])

    @property
    def answer_name(self) -> str:
        return f"{self._answer_version.name} ({self._answer_version.impl})"

    @cached_property
    def _evidence(self) -> IndexedEvidenceAdapter:
        """The report text and figure images of the figure index the answer version names."""
        index = self._settings.versions_dir / "answer" / self._answer_version.params["index"]
        return IndexedEvidenceAdapter(FigureIndex.load(index), self._settings.reports_dir)

    @cached_property
    def reports(self) -> ReportService:
        return ReportService(self._evidence)

    @cached_property
    def photo_answers(self) -> PhotoAnswerService:
        """Finds the report figures nearest a photo and answers from them; loads no model yet."""
        version = self._answer_version
        return PhotoAnswerService(
            failures=self.failures,
            evidence=self._evidence,
            answerer=ANSWERERS[version.impl].build(self._settings, version.params),
            trace=self._trace(),
            answer_name=self.answer_name,
            figures=version.params.get("figures", 3),
            images=version.params.get("images", 2),
            figure_side=version.params.get("figure_side", 768),
        )

    @cached_property
    def traces(self) -> TraceService:
        return TraceService(trace=self._trace())

    def _trace(self) -> SqliteTraceAdapter:
        """One trace adapter, shared by the services, even when threads ask at once."""
        with self._lock:
            if self._trace_adapter is None:
                self._trace_adapter = SqliteTraceAdapter(self._settings.trace_path)
                self._stack.callback(self._trace_adapter.close)
            return self._trace_adapter


@contextmanager
def open_services(settings: Settings) -> Iterator[Services]:
    with ExitStack() as stack:
        yield Services(settings, stack)
