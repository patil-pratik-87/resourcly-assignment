import hashlib
import json
import os
import threading
import tomllib
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field, replace
from functools import cached_property
from pathlib import Path
from typing import Any

from resourcly.adapters.gold_store import JsonGoldStoreAdapter
from resourcly.adapters.pdf_pages import PyMuPDFPageAdapter
from resourcly.adapters.request_store import JsonRequestStoreAdapter
from resourcly.adapters.shuffled_figures import ShuffledFiguresAdapter
from resourcly.adapters.sqlite_trace import SqliteTraceAdapter
from resourcly.adapters.stub_router import StubRouteAdapter
from resourcly.adapters.text_reader import PyMuPDFTextReaderAdapter
from resourcly.adapters.thread_jobs import ThreadJobsAdapter
from resourcly.adapters.upload_store import FileUploadStoreAdapter
from resourcly.agent import AgentService, recover
from resourcly.errors import InvalidVersion, NotFound
from resourcly.ports import RouterPort
from resourcly.services import (
    DrawingService,
    FailureService,
    GoldService,
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
    ui_dist: Path = PROJECT_ROOT / "src" / "frontend" / "annotation" / "dist"
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
            "reader": "textlayer-v0",
            "router": "stub-v0",
            "failure": "shuffled-v0",
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
            ui_dist=Path(os.environ.get("RESOURCLY_UI_DIST", defaults.ui_dist)),
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
    """A named implementation of one component and its settings, from
    versions/<component>/<name>.toml."""

    component: str
    name: str
    impl: str
    description: str
    params: dict[str, Any]

    @property
    def hash(self) -> str:
        config = {"component": self.component, "impl": self.impl, "params": self.params}
        text = json.dumps(config, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(text.encode()).hexdigest()[:12]


@dataclass(frozen=True)
class Implementation:
    """How to build one implementation of a component, and the settings a version may give it."""

    build: Callable[[Settings, dict[str, Any]], Any]
    settings: tuple[str, ...] = ()
    required: tuple[str, ...] = ()


READERS: dict[str, Implementation] = {
    "textlayer": Implementation(
        lambda settings, params: PyMuPDFTextReaderAdapter(settings.drawings_dir)
    ),
}
ROUTERS: dict[str, Implementation] = {
    # A model-free stand-in, for tests and machines without the router's models.
    "stub": Implementation(
        lambda settings, params: [StubRouteAdapter(**params)], settings=("min_paths",)
    ),
}
FINDERS: dict[str, Implementation] = {
    # No model: a fixed random order of the report figures, the floor for the failure finders.
    "shuffled": Implementation(
        lambda settings, params: ShuffledFiguresAdapter(
            settings.reports_dir / "sections.toml", **params
        ),
        settings=("seed",),
    ),
}
IMPLEMENTATIONS: dict[str, dict[str, Implementation]] = {
    "reader": READERS,
    "router": ROUTERS,
    "failure": FINDERS,
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
    return Version(component, name, impl, description, params)


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
    def failures(self) -> FailureService:
        finder = load_version(self._settings, "failure", self._settings.versions["failure"])
        return FailureService(
            finder=FINDERS[finder.impl].build(self._settings, finder.params),
            trace=self._trace(),
            finder_name=f"{finder.name} ({finder.impl})",
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
