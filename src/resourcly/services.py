import hashlib
import logging
import re
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from resourcly.errors import InvalidDocument, NotFound
from resourcly.models import (
    Attachment,
    DrawingSummary,
    GoldDocument,
    Issue,
    LayerVerdict,
    Reading,
    RequestTrace,
    Route,
    Routing,
    TitleBlock,
    TraceEvent,
    guess_media_type,
    undefined_datums,
    validate_document,
)
from resourcly.ports import (
    DrawingPagePort,
    GoldStorePort,
    Progress,
    ReaderPort,
    RouteLayerPort,
    Source,
    Splits,
    TracePort,
)

log = logging.getLogger(__name__)

DRAWING_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class GoldService:
    def __init__(self, store: GoldStorePort, pages: DrawingPagePort):
        self.store = store
        self.pages = pages

    def list_drawings(self) -> list[DrawingSummary]:
        gold = self.store.list_drawings()
        pdfs = set(self.pages.list_drawings())
        return [
            self._summary(name, gold.get(name), name in pdfs) for name in sorted(pdfs | gold.keys())
        ]

    def load(self, drawing: str) -> dict[str, Any]:
        _check_name(drawing)
        if self.store.exists(drawing):
            return self.store.load(drawing)
        return GoldDocument(
            drawing=drawing, page_count=self.pages.page_count(drawing), title_block=TitleBlock()
        ).model_dump(mode="json")

    def check(self, drawing: str, document: Any) -> list[Issue]:
        _check_name(drawing)
        _, issues = self._validate(drawing, document)
        return issues

    def save(self, drawing: str, document: Any) -> GoldDocument:
        _check_name(drawing)
        valid, issues = self._validate(drawing, document)
        if valid is None:
            raise InvalidDocument(issues)
        self.store.save(drawing, valid)
        return valid

    def check_all(self) -> dict[str, list[Issue]]:
        results = {}
        for drawing in self.store.list_drawings():
            try:
                results[drawing] = self.check(drawing, self.store.load(drawing))
            except InvalidDocument as error:
                results[drawing] = error.issues
        return results

    def splits(self) -> Splits:
        return self.store.load_splits()

    def route_cases(self) -> list[dict[str, Any]]:
        return self.store.load_route_cases()

    def route_file_exists(self, file: str) -> bool:
        return self.store.file_exists(f"routes/{file}")

    def route_attachment(self, file: str) -> Attachment:
        """A file the router gold names, as the attachment of a request."""
        data = self.store.load_file(f"routes/{file}")
        return Attachment(file, guess_media_type(file, data), data)

    def render_page(self, drawing: str, page: int, dpi: int) -> bytes:
        _check_name(drawing)
        return self.pages.render(drawing, page, dpi)

    def _validate(self, drawing: str, document: Any) -> tuple[GoldDocument | None, list[Issue]]:
        valid, issues = validate_document(document)
        if valid is None:
            return None, issues
        if valid.drawing != drawing:
            issues.append(
                Issue(loc=["drawing"], message=f"must be '{drawing}', the file it is stored as")
            )
        if drawing in self.pages.list_drawings():
            pages = self.pages.page_count(drawing)
            if valid.page_count != pages:
                issues.append(Issue(loc=["page_count"], message=f"the PDF has {pages} page(s)"))
        # Partial gold lists a few values only, and a page-limited document covers only some
        # pages, so their frames may name datums defined elsewhere.
        partial = self.store.list_drawings().get(drawing) == "partial"
        if not partial and valid.page_coverage is None:
            issues.extend(undefined_datums(valid))
        return (None, issues) if issues else (valid, [])

    def _summary(self, drawing: str, source: Source | None, has_pdf: bool) -> DrawingSummary:
        values = approved = issues = 0
        page_count = self.pages.page_count(drawing) if has_pdf else 0
        if source is not None:
            try:
                document = self.store.load(drawing)
                found = self.check(drawing, document)
                rows = document.get("values", []) if isinstance(document, dict) else []
                values = len(rows)
                approved = sum(
                    1 for row in rows if isinstance(row, dict) and row.get("status") == "approved"
                )
                issues = len(found)
            except InvalidDocument as error:
                issues = len(error.issues)
        return DrawingSummary(
            drawing=drawing,
            page_count=page_count,
            has_gold=source is not None,
            source=source,
            values=values,
            approved=approved,
            issues=issues,
        )


class DrawingService:
    def __init__(self, reader: ReaderPort, trace: TracePort, reader_name: str):
        self.reader = reader
        self.trace = trace
        self.reader_name = reader_name

    def read(
        self, drawing: str, request_id: str | None = None, progress: Progress | None = None
    ) -> Reading:
        """Read a drawing's values; the call is traced under request_id, or a new one.

        The reader calls `progress`, when given, before each step of the read.

        The trace is recorded after the read. A trace that cannot be recorded is logged and
        changes neither the reading nor the reader's error.
        """
        _check_name(drawing)
        request_id = request_id or uuid.uuid4().hex
        started, began = now(), time.perf_counter()
        document = None
        issues: list[Issue] = []
        error = None
        try:
            document = self.reader.read(drawing, progress)
            _, issues = validate_document(document, gold=False)
        except Exception as exc:
            error = exc
        values = document.get("values") if isinstance(document, dict) else None
        self._record(
            TraceEvent(
                request_id=request_id,
                step="drawings.read",
                called=f"reader {self.reader_name}",
                input={"drawing": drawing},
                output={
                    "values": len(values) if isinstance(values, list) else 0,
                    "schema_issues": len(issues),
                },
                error=f"{type(error).__name__}: {error}" if error else None,
                started_at=started,
                duration_ms=round((time.perf_counter() - began) * 1000, 1),
            )
        )
        if error:
            raise error
        return Reading(request_id=request_id, drawing=drawing, document=document, issues=issues)

    def _record(self, event: TraceEvent) -> None:
        try:
            self.trace.record(event)
        except Exception:
            log.exception("could not record the trace of request %s", event.request_id)


class RouterService:
    """Picks the case of a request by asking each layer in turn, from the cheapest.

    The first layer that gives a route decides, and the later layers are not asked. A request
    that no layer is sure of fits no case. Every layer asked is traced under the request id with
    what it made of the request, so `evals show --request` shows which layer decided and why. The
    user's text is traced by length only, and it never changes the route.
    """

    def __init__(self, layers: list[RouteLayerPort], trace: TracePort, router_name: str):
        self.layers = layers
        self.trace = trace
        self.router_name = router_name

    def route(
        self, text: str | None, attachment: Attachment | None, request_id: str | None = None
    ) -> Routing:
        request_id = request_id or uuid.uuid4().hex
        began = time.perf_counter()
        request = {"text_chars": len(text or ""), "attachment": _described(attachment)}
        last = None
        for layer in self.layers:
            last = self._ask(layer, attachment, request_id, request)
            if last.route is not None:
                return self._routing(request_id, layer.name, last, began)
        reason = f"no layer was sure; the last said: {last.reason}" if last else "no layers"
        return self._routing(request_id, "none", LayerVerdict(Route.OTHER, reason, None, {}), began)

    def _ask(
        self,
        layer: RouteLayerPort,
        attachment: Attachment | None,
        request_id: str,
        request: dict[str, Any],
    ) -> LayerVerdict:
        started, began = now(), time.perf_counter()
        try:
            verdict = layer.decide(attachment)
        except Exception as error:
            self._record(layer, request_id, request, {"decided": False}, error, started, began)
            raise
        output = {
            "decided": verdict.route is not None,
            "route": verdict.route.value if verdict.route else None,
            "confidence": verdict.confidence,
            "reason": verdict.reason,
            "probabilities": verdict.probabilities,
        }
        self._record(layer, request_id, request, output, None, started, began)
        return verdict

    def _record(
        self,
        layer: RouteLayerPort,
        request_id: str,
        request: dict[str, Any],
        output: dict[str, Any],
        error: Exception | None,
        started: str,
        began: float,
    ) -> None:
        event = TraceEvent(
            request_id=request_id,
            step=f"route.{layer.name}",
            called=f"router {self.router_name}: {layer.called}",
            input=request,
            output=output,
            error=f"{type(error).__name__}: {error}" if error else None,
            started_at=started,
            duration_ms=round((time.perf_counter() - began) * 1000, 1),
        )
        try:
            self.trace.record(event)
        except Exception:
            log.exception("could not record the trace of request %s", request_id)

    @staticmethod
    def _routing(request_id: str, layer: str, verdict: LayerVerdict, began: float) -> Routing:
        return Routing(
            request_id=request_id,
            route=verdict.route,
            layer=layer,
            confidence=verdict.confidence,
            reason=verdict.reason,
            probabilities=verdict.probabilities,
            elapsed_ms=round((time.perf_counter() - began) * 1000, 1),
        )


def _described(attachment: Attachment | None) -> dict[str, Any] | None:
    if attachment is None:
        return None
    return {
        "name": attachment.name,
        "media_type": attachment.media_type,
        "bytes": len(attachment.data),
        "sha256": hashlib.sha256(attachment.data).hexdigest(),
    }


class TraceService:
    def __init__(self, trace: TracePort):
        self.trace = trace

    def lookup(self, request_id: str) -> RequestTrace:
        events = self.trace.find(request_id)
        if not events:
            raise NotFound(f"no request '{request_id}'")
        return RequestTrace(request_id=request_id, events=events)


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _check_name(drawing: str) -> None:
    if not DRAWING_NAME.match(drawing):
        raise NotFound(f"'{drawing}' is not a drawing name")
