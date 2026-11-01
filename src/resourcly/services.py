import logging
import re
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from resourcly.errors import InvalidDocument, NotFound
from resourcly.models import (
    DrawingSummary,
    GoldDocument,
    Issue,
    Reading,
    TitleBlock,
    TraceEvent,
    undefined_datums,
    validate_document,
)
from resourcly.ports import (
    DrawingPagePort,
    GoldStorePort,
    Progress,
    ReaderPort,
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


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _check_name(drawing: str) -> None:
    if not DRAWING_NAME.match(drawing):
        raise NotFound(f"'{drawing}' is not a drawing name")
