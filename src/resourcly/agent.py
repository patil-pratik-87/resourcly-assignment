"""The agent a user chats with: each message becomes one request, and each of its files one item.

`submit` keeps the files and returns at once. A background job then routes every item: a drawing
is queued for the reader, and the other cases get their reply straight away. Reads run after
routing, one at a time, and report their progress into the request record, which the chat polls.
Every step is traced under the request id when it ends, so the trace of a running request is
already readable.
"""

import hashlib
import logging
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import partial
from pathlib import Path
from typing import Any

from resourcly.errors import EmptyRequest, ModelNotCached, NotFound, UnsupportedUpload
from resourcly.models import (
    ACTIVE,
    Attachment,
    ReadProgress,
    RequestItem,
    RequestRecord,
    Route,
    Routing,
    TraceEvent,
)
from resourcly.ports import (
    DrawingPagePort,
    JobsPort,
    RequestStorePort,
    RouterPort,
    TracePort,
    UploadStorePort,
)
from resourcly.services import DrawingService, now

log = logging.getLogger(__name__)

ROUTE_JOB, READ_JOB = 0, 1
# The reply for each route other than a drawing; none of them has an answerer yet.
REPLIES = {
    Route.PHOTO: (
        "This looks like a photo of a part. Saying what is wrong with it and what to do, from the"
        " NTSB reports, is not available yet."
    ),
    Route.TEXT: (
        "Answering questions from the NTSB reports is not available yet. Attach a technical"
        " drawing, or many at once, and each comes back as JSON with every value on it."
    ),
    Route.OTHER: (
        "This fits neither case the agent handles: a technical drawing to turn into JSON, or a"
        " photo of a damaged part to diagnose."
    ),
}
NO_ANSWERER = {
    Route.PHOTO: "nothing: picture answering is not available yet",
    Route.TEXT: "nothing: text answering is not available yet",
    Route.OTHER: "nothing: no case applies",
}
INTERRUPTED = "The server stopped before this finished. Send the file again."


class AgentService:
    def __init__(
        self,
        uploads: UploadStorePort,
        requests: RequestStorePort,
        router: RouterPort,
        router_name: str,
        drawings_in: Callable[[Path], DrawingService],
        pages_in: Callable[[Path], DrawingPagePort],
        trace: TracePort,
        jobs: JobsPort,
    ):
        self.uploads = uploads
        self.requests = requests
        self.router = router
        self.router_name = router_name
        self.drawings_in = drawings_in
        self.pages_in = pages_in
        self.trace = trace
        self.jobs = jobs
        self._lock = threading.Lock()

    def submit(self, text: str, files: list[tuple[str, bytes]]) -> RequestRecord:
        """Keep the message and its files, and start routing them in the background."""
        text = text.strip()
        if not text and not files:
            raise EmptyRequest("Send some text, a file, or both.")
        request_id = uuid.uuid4().hex
        record = RequestRecord(request_id=request_id, text=text, created_at=now(), items=[])
        with self._step(request_id, "requests.receive", "agent") as step:
            step["input"] = {**_traced_text(text), "files": [name for name, _ in files]}
            step["output"] = {"request_id": request_id}
        for index, (name, content) in enumerate(files, start=1):
            record.items.append(self._keep(request_id, index, name, content))
        if not files:
            record.items.append(RequestItem(item_id="message", kind="text", name=_shorten(text)))
        self.requests.save(record)
        self.jobs.submit(lambda: self._route(request_id), priority=ROUTE_JOB)
        return record

    def load(self, request_id: str) -> RequestRecord:
        return self.requests.load(request_id)

    def list(self, limit: int) -> list[RequestRecord]:
        return self.requests.list(limit)

    def result(self, request_id: str, item_id: str) -> dict[str, Any]:
        return self.requests.load_result(request_id, item_id)

    def page(self, request_id: str, item_id: str, page: int, dpi: int) -> bytes:
        """One page of an uploaded file as a PNG; an image is kept as a one-page PDF too."""
        record = self.requests.load(request_id)
        if not any(item.item_id == item_id and item.kind == "file" for item in record.items):
            raise NotFound(f"request {request_id} has no file {item_id}")
        pages = self.pages_in(self.uploads.folder(request_id))
        try:
            return pages.render(item_id, page, dpi)
        finally:
            pages.close()

    def _keep(self, request_id: str, index: int, name: str, content: bytes) -> RequestItem:
        with self._step(request_id, "uploads.save", "upload store") as step:
            step["input"] = {"name": name, "bytes": len(content)}
            try:
                stored = self.uploads.save_file(request_id, name, content)
            except UnsupportedUpload as error:
                step["input"]["item"] = f"rejected-{index}"
                step["error"] = f"UnsupportedUpload: {error}"
                item = RequestItem(
                    item_id=f"rejected-{index}", kind="file", name=name, size=len(content)
                )
                _fail(item, str(error))
                return item
            step["input"]["item"] = stored.item_id
            step["output"] = {"media_type": stored.media_type, "pages": stored.pages}
        return RequestItem(
            item_id=stored.item_id,
            kind="file",
            name=stored.name,
            media_type=stored.media_type,
            size=stored.size,
            pages=stored.pages,
        )

    def _route(self, request_id: str) -> None:
        record = self.requests.load(request_id)
        for item in record.items:
            if item.status != "routing":
                continue
            decision = self._decide(request_id, record.text, item)
            with self._update(request_id, item.item_id) as current:
                if decision is None:
                    _fail(current, "The router could not decide; see the trace.")
                elif decision.route == Route.DRAWING:
                    current.route, current.status = decision, "queued"
                else:
                    current.route = decision
            if decision is None:
                continue
            if decision.route == Route.DRAWING:
                self.jobs.submit(partial(self._read, request_id, item.item_id), priority=READ_JOB)
            else:
                self._answer(request_id, item, decision)

    def _decide(self, request_id: str, text: str, item: RequestItem) -> Routing | None:
        """The router's answer for one item; the router traces each layer it asks on its own."""
        attachment = None
        if item.kind == "file":
            data, media_type = self.uploads.original(request_id, item.item_id)
            attachment = Attachment(item.name, media_type, data)
        with self._step(request_id, "router.route", f"router {self.router_name}") as step:
            step["input"] = {
                "item": item.item_id,
                **_traced_text(text),
                "file": item.name if attachment else None,
            }
            try:
                decision = self.router.route(text or None, attachment, request_id)
            except Exception as error:
                step["error"] = f"{type(error).__name__}: {error}"
                return None
            step["output"] = decision.model_dump(mode="json")
            return decision

    def _answer(self, request_id: str, item: RequestItem, decision: Routing) -> None:
        item_id = item.item_id
        reply = REPLIES[decision.route]
        with self._step(request_id, "answer.reply", NO_ANSWERER[decision.route]) as step:
            step["input"] = {"item": item_id, "route": decision.route.value}
            step["output"] = {"reply": reply}
        with self._update(request_id, item_id) as item:
            item.status, item.reply, item.finished_at = "answered", reply, now()

    def _read(self, request_id: str, item_id: str) -> None:
        with self._update(request_id, item_id) as item:
            item.status, item.started_at = "reading", now()

        def report(progress: ReadProgress) -> None:
            with self._update(request_id, item_id) as item:
                item.progress = progress

        try:
            drawings = self.drawings_in(self.uploads.folder(request_id))
            reading = drawings.read(item_id, request_id=request_id, progress=report)
            self.requests.save_result(request_id, item_id, reading.document)
        except Exception as error:
            if isinstance(error, ModelNotCached):  # its message says how to fix it; no traceback
                log.warning("reading %s of request %s failed: %s", item_id, request_id, error)
            else:
                log.exception("reading %s of request %s failed", item_id, request_id)
            with self._update(request_id, item_id) as item:
                _fail(item, str(error) or type(error).__name__)
            return
        values = reading.document.get("values")
        with self._update(request_id, item_id) as item:
            item.status, item.progress, item.finished_at = "done", None, now()
            item.values = len(values) if isinstance(values, list) else 0
            item.issues = len(reading.issues)

    @contextmanager
    def _update(self, request_id: str, item_id: str) -> Iterator[RequestItem]:
        """Change one item of a stored request; one writer at a time."""
        with self._lock:
            record = self.requests.load(request_id)
            item = next(item for item in record.items if item.item_id == item_id)
            yield item
            self.requests.save(record)

    @contextmanager
    def _step(self, request_id: str, step: str, called: str) -> Iterator[dict[str, Any]]:
        """Trace one step; the body fills in `input`, `output` and `error`."""
        found: dict[str, Any] = {"input": {}, "output": {}, "error": None}
        started, began = now(), time.perf_counter()
        try:
            yield found
        except Exception as error:
            found["error"] = f"{type(error).__name__}: {error}"
            raise
        finally:
            event = TraceEvent(
                request_id=request_id,
                step=step,
                called=called,
                input=found["input"],
                output=found["output"],
                error=found["error"],
                started_at=started,
                duration_ms=round((time.perf_counter() - began) * 1000, 1),
            )
            try:
                self.trace.record(event)
            except Exception:
                log.exception("could not record the trace of request %s", request_id)


def recover(requests: RequestStorePort) -> None:
    """Mark the work a previous server left unfinished as failed; its jobs died with it.

    Only the server calls this when it starts, never the CLI, which may run beside a live server.
    """
    for record in requests.list(limit=1_000_000):
        if record.status != "working":
            continue
        for item in record.items:
            if item.status in ACTIVE:
                _fail(item, INTERRUPTED)
        requests.save(record)


def _traced_text(text: str) -> dict[str, Any]:
    """The message text as the trace keeps it: its length and hash, never the words.

    The words live once, in the request record, which is the chat history.
    """
    return {"text_chars": len(text), "text_sha256": hashlib.sha256(text.encode()).hexdigest()}


def _fail(item: RequestItem, error: str) -> None:
    item.status, item.error, item.progress, item.finished_at = "failed", error, None, now()


def _shorten(text: str, limit: int = 80) -> str:
    line = " ".join(text.split())
    return line if len(line) <= limit else f"{line[: limit - 1]}…"
