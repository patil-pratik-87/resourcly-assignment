"""The agent a user chats with: each message becomes one request, and each of its files one item.

`submit` keeps the files and returns at once. A background job then routes every item: a drawing
is queued for the reader, a photo is queued for an answer from the reports, and the other cases
get their reply straight away. Reads and photo answers run after routing, one at a time, and
report their state into the request record, which the chat polls. When the text sent with files
asks for more than reading them, a drawing's question is answered after its read, on a lane of
its own, so an answer never waits behind other reads, only behind the one model call running.

The messages of a conversation share its id, and the last turns of it go into each answer's
prompt as text. A message without files may be about earlier items or values: it is answered
from their stored JSON or photo matches, never read again, and a value the user picked is the
answer itself, with no model call.
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

from resourcly.answers import PhotoAnswerService, render_reply
from resourcly.errors import (
    EmptyRequest,
    ModelNotCached,
    NotFound,
    UnknownTarget,
    UnsupportedUpload,
)
from resourcly.models import (
    ACTIVE,
    Attachment,
    EvidenceValue,
    Issue,
    ItemRef,
    Reading,
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
from resourcly.questions import QuestionService
from resourcly.services import DrawingService, now

log = logging.getLogger(__name__)

ROUTE_JOB, READ_JOB = 0, 1
# The reply for a file that fits no case, which has no answerer.
REPLIES = {
    Route.OTHER: (
        "This fits neither case the agent handles: a technical drawing to turn into JSON, or a"
        " photo of a damaged part to diagnose."
    ),
}
NO_ANSWERER = {Route.OTHER: "nothing: no case applies"}
INTERRUPTED = "The server stopped before this finished. Send the file again."
NOT_ANSWERED = "The JSON is read, but the question could not be answered:"
CROP_MARGIN = 6  # points around a value's box in its crop
EARLIER_TURNS = 3  # the turns of the conversation an answer's prompt holds"


class AgentService:
    def __init__(
        self,
        uploads: UploadStorePort,
        requests: RequestStorePort,
        router: RouterPort,
        router_name: str,
        drawings_in: Callable[[Path], DrawingService],
        photos: Callable[[], PhotoAnswerService],
        questions: Callable[[], QuestionService],
        pages_in: Callable[[Path], DrawingPagePort],
        trace: TracePort,
        jobs: JobsPort,
        answer_jobs: JobsPort,
        reader_key: Callable[[], str] = lambda: "reader",
    ):
        self.uploads = uploads
        self.requests = requests
        self.router = router
        self.router_name = router_name
        self.drawings_in = drawings_in
        self.photos = photos
        self.questions = questions
        self.pages_in = pages_in
        self.trace = trace
        self.jobs = jobs
        self.answer_jobs = answer_jobs
        self.reader_key = reader_key  # names the reader version, for the read cache
        self._lock = threading.Lock()

    def submit(
        self,
        text: str,
        files: list[tuple[str, bytes]],
        conversation_id: str | None = None,
        about: list[str] = (),
    ) -> RequestRecord:
        """Keep the message and its files, and start routing them in the background.

        The message joins the conversation named, or starts one. `about` names earlier items or
        values a message without files asks about; it must name what the store holds.
        """
        text = text.strip()
        if not text and not files:
            raise EmptyRequest("Send some text, a file, or both.")
        about = list(about) if not files else []
        for ref in about:
            try:
                self._target(ref)
            except NotFound as error:
                raise UnknownTarget(
                    f"The message is about something earlier that is gone: {error}."
                ) from error
        request_id = uuid.uuid4().hex
        record = RequestRecord(
            request_id=request_id,
            text=text,
            created_at=now(),
            items=[],
            conversation_id=conversation_id or uuid.uuid4().hex,
            about=about,
        )
        with self._step(request_id, "requests.receive", "agent") as step:
            step["input"] = {
                **_traced_text(text),
                "files": [name for name, _ in files],
                "conversation_id": record.conversation_id,
                "about": about,
            }
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

    def crop(self, request_id: str, item_id: str, value_id: str, dpi: int) -> bytes:
        """A value of a read drawing cut from its page, with CROP_MARGIN points around it."""
        record = self.requests.load(request_id)
        if not any(item.item_id == item_id and item.kind == "file" for item in record.items):
            raise NotFound(f"request {request_id} has no file {item_id}")
        values = self.requests.load_result(request_id, item_id).get("values") or []
        value = next((v for v in values if isinstance(v, dict) and v.get("id") == value_id), None)
        if value is None or not isinstance(value.get("page"), int):
            raise NotFound(f"{item_id} has no value {value_id}")
        bbox = value.get("bbox")
        if not isinstance(bbox, list) or len(bbox) != 4 or bbox == [0, 0, 1, 1]:
            raise NotFound(f"{value_id} has no box on its page")
        pages = self.pages_in(self.uploads.folder(request_id))
        try:
            width, height = pages.page_size(item_id, value["page"])
            x0, y0, x1, y1 = bbox
            clip = (
                x0 * width - CROP_MARGIN,
                y0 * height - CROP_MARGIN,
                x1 * width + CROP_MARGIN,
                y1 * height + CROP_MARGIN,
            )
            return pages.render(item_id, value["page"], dpi, clip)
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
        if record.text and any(item.kind == "file" for item in record.items):
            record.needs_answer = self._needs_answer(request_id, record.text)
            self.requests.save(record)
        for item in record.items:
            if item.status != "routing":
                continue
            decision = self._decide(request_id, record.text, item)
            with self._update(request_id, item.item_id) as current:
                if decision is None:
                    _fail(current, "The router could not decide; see the trace.")
                elif _queued(item, decision):
                    current.route, current.status = decision, "queued"
                else:
                    current.route = decision
            if decision is None:
                continue
            if decision.route == Route.DRAWING:
                self.jobs.submit(partial(self._read, request_id, item.item_id), priority=READ_JOB)
            elif _queued(item, decision):
                self.jobs.submit(
                    partial(self._answer_photo, request_id, item.item_id), priority=READ_JOB
                )
            else:
                self._answer(request_id, item, decision)
        self._ask_on_message(request_id)

    def _ask_on_message(self, request_id: str) -> None:
        """Give the question a card of its own when no single file's card can hold its answer.

        That is a question over several drawings, answered once they are read from all their
        values, or one sent with files that fit no case, answered from the reports.
        """
        record = self.requests.load(request_id)
        routes = [item.route.route for item in record.items if item.route]
        drawings, photos = routes.count(Route.DRAWING), routes.count(Route.PHOTO)
        if not record.needs_answer or drawings == 1 or (photos and not drawings):
            return
        item_id = _free_id({item.item_id for item in record.items}, "message")
        reason = (
            "The text asks a question of its own, answered once from the values of every drawing."
            if drawings
            else "The text asks a question the files cannot answer, so the reports answer it."
        )
        message = RequestItem(
            item_id=item_id,
            kind="text",
            name=_shorten(record.text),
            route=Routing(
                request_id=request_id,
                route=Route.TEXT,
                layer="gate",
                confidence=None,
                reason=reason,
                probabilities={},
                elapsed_ms=0,
            ),
        )
        message.status = "queued" if drawings else "answering"
        message.started_at = None if drawings else now()
        with self._lock:
            record = self.requests.load(request_id)
            record.items.append(message)
            self.requests.save(record)
        if not drawings:
            self.answer_jobs.submit(partial(self._answer_message, request_id, item_id))

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

    def _needs_answer(self, request_id: str, text: str) -> bool:
        """Whether the text asks for more than reading the files; no when the gate fails."""
        try:
            return self.questions().needs_answer(text, request_id)
        except Exception as error:
            log.warning("the answer gate of request %s failed: %s", request_id, error)
            return False

    def _answer(self, request_id: str, item: RequestItem, decision: Routing) -> None:
        if decision.route == Route.TEXT and item.kind == "text":
            with self._update(request_id, item.item_id) as current:
                current.status, current.started_at = "answering", now()
            self.answer_jobs.submit(partial(self._answer_message, request_id, item.item_id))
            return
        item_id = item.item_id
        reply = REPLIES.get(decision.route, REPLIES[Route.OTHER])
        with self._step(request_id, "answer.reply", NO_ANSWERER[Route.OTHER]) as step:
            step["input"] = {"item": item_id, "route": decision.route.value}
            step["output"] = {"reply": reply}
        with self._update(request_id, item_id) as item:
            item.status, item.reply, item.finished_at = "answered", reply, now()

    def _answer_photo(self, request_id: str, item_id: str) -> None:
        """Say what is wrong with the part in a photo and what to do, from the reports.

        The message's text is the question when it asks for more than reading the files.
        """
        with self._update(request_id, item_id) as item:
            item.status, item.started_at = "answering", now()
            record = self.requests.load(request_id)
            name, text = item.name, record.text if record.needs_answer else ""
        try:
            data, media_type = self.uploads.original(request_id, item_id)
            answer = self.photos().answer(Attachment(name, media_type, data), text, request_id)
        except Exception as error:
            if isinstance(error, ModelNotCached):
                log.warning("answering %s of request %s failed: %s", item_id, request_id, error)
            else:
                log.exception("answering %s of request %s failed", item_id, request_id)
            with self._update(request_id, item_id) as item:
                _fail(item, str(error) or type(error).__name__)
            return
        with self._update(request_id, item_id) as item:
            item.status, item.answer, item.finished_at = "answered", answer, now()
            item.reply = render_reply(answer)

    def _read(self, request_id: str, item_id: str) -> None:
        with self._update(request_id, item_id) as item:
            item.status, item.started_at = "reading", now()

        def report(progress: ReadProgress) -> None:
            with self._update(request_id, item_id) as item:
                item.progress = progress

        try:
            reading = self._cached_read(request_id, item_id)
            if reading is None:
                drawings = self.drawings_in(self.uploads.folder(request_id))
                reading = drawings.read(item_id, request_id=request_id, progress=report)
                self.requests.save_cached(
                    self._read_key(request_id, item_id),
                    {
                        "document": reading.document,
                        "issues": [issue.model_dump() for issue in reading.issues],
                    },
                )
            self.requests.save_result(request_id, item_id, reading.document)
        except Exception as error:
            if isinstance(error, ModelNotCached):  # its message says how to fix it; no traceback
                log.warning("reading %s of request %s failed: %s", item_id, request_id, error)
            else:
                log.exception("reading %s of request %s failed", item_id, request_id)
            with self._update(request_id, item_id) as item:
                _fail(item, str(error) or type(error).__name__)
            self._after_reads(request_id)
            return
        values = reading.document.get("values")
        record = self.requests.load(request_id)
        alone = record.needs_answer is True and sum(map(_is_drawing, record.items)) == 1
        with self._update(request_id, item_id) as item:
            item.status, item.progress, item.finished_at = "done", None, now()
            item.values = len(values) if isinstance(values, list) else 0
            item.issues = len(reading.issues)
            if alone:
                item.status = "answering"
        if alone:
            self.answer_jobs.submit(partial(self._answer_drawing, request_id, item_id))
        else:
            self._after_reads(request_id)

    def _read_key(self, request_id: str, item_id: str) -> str:
        """The file's SHA-256 and the reader version's name and hash: the same file read by the
        same reader gives the same JSON."""
        pdf = (self.uploads.folder(request_id) / f"{item_id}.pdf").read_bytes()
        return f"{hashlib.sha256(pdf).hexdigest()}-{self.reader_key()}"

    def _cached_read(self, request_id: str, item_id: str) -> Reading | None:
        """The JSON a read of the same file by the same reader kept, traced as the read."""
        key = self._read_key(request_id, item_id)
        cached = self.requests.load_cached(key)
        if cached is None:
            return None
        document = {**cached["document"], "drawing": item_id}
        values = document.get("values")
        with self._step(request_id, "drawings.read", "read cache") as step:
            step["input"] = {"drawing": item_id, "key": key}
            step["output"] = {
                "values": len(values) if isinstance(values, list) else 0,
                "issues": len(cached["issues"]),
            }
        return Reading(
            request_id=request_id,
            drawing=item_id,
            document=document,
            issues=[Issue.model_validate(issue) for issue in cached["issues"]],
        )

    def _after_reads(self, request_id: str) -> None:
        """Once every drawing of the message is read or failed, answer its question over them."""
        record = self.requests.load(request_id)
        drawings = [item for item in record.items if _is_drawing(item)]
        waiting = [item for item in record.items if item.kind == "text" and item.status == "queued"]
        if waiting and len(drawings) > 1 and all(i.status not in ACTIVE for i in drawings):
            self.answer_jobs.submit(partial(self._answer_drawings, request_id, waiting[0].item_id))

    def _answer_message(self, request_id: str, item_id: str) -> None:
        """Answer a message without files: from the earlier items or values it is about, or else
        from the report passages a search finds."""
        record = self.requests.load(request_id)
        try:
            targets = [self._target(ref) for ref in record.about]
            values = [value for _, value in targets if value is not None]
            items = [item for item, value in targets if value is None]
            if not targets:
                answer = self.questions().text(
                    record.text, request_id, _earlier(self.requests, record)
                )
                photo = None
            elif values:
                answer = self.questions().value(record.text, values, request_id)
                photo = None
            elif any(item.route and item.route.route == Route.DRAWING for _, item in items):
                drawings = [(ref, item) for ref, item in items if item.route.route == Route.DRAWING]
                answer = self.questions().drawing(
                    record.text,
                    [
                        (ref, self.requests.load_result(ref.request_id, ref.item_id), False)
                        for ref, _ in drawings
                    ],
                    request_id,
                    _earlier(self.requests, record),
                )
                photo = None
            else:
                ref, item = items[0]
                data, media_type = self.uploads.original(ref.request_id, ref.item_id)
                photo = self.photos().answer(
                    Attachment(item.name, media_type, data),
                    record.text,
                    request_id,
                    matches=item.answer.figures if item.answer else None,
                )
                answer = None
        except Exception as error:
            log.warning("answering request %s failed: %s", request_id, error)
            with self._update(request_id, item_id) as current:
                _fail(current, str(error) or type(error).__name__)
            return
        with self._update(request_id, item_id) as current:
            current.status, current.finished_at = "answered", now()
            current.qa, current.answer = answer, photo
            current.reply = answer.reply if answer else render_reply(photo)

    def _answer_drawings(self, request_id: str, item_id: str) -> None:
        """Answer the message's question from the values of all its drawings that were read."""
        with self._update(request_id, item_id) as current:
            current.status, current.started_at = "answering", now()
        record = self.requests.load(request_id)
        read = [i for i in record.items if _is_drawing(i) and i.status == "done"]
        try:
            if not read:
                raise ValueError("no drawing of the message could be read")
            answer = self.questions().drawing(
                record.text,
                [
                    (
                        ItemRef(request_id, i.item_id),
                        self.requests.load_result(request_id, i.item_id),
                        False,
                    )
                    for i in read
                ],
                request_id,
                _earlier(self.requests, record),
            )
        except Exception as error:
            log.warning("answering request %s failed: %s", request_id, error)
            with self._update(request_id, item_id) as current:
                _fail(current, str(error) or type(error).__name__)
            return
        with self._update(request_id, item_id) as current:
            current.status, current.finished_at = "answered", now()
            current.qa, current.reply = answer, answer.reply

    def _target(self, ref: str) -> tuple[tuple[ItemRef, RequestItem], EvidenceValue | None]:
        """The earlier item a ref names, and its value when it names one; NotFound otherwise."""
        parts = ref.split("/")
        if len(parts) not in (2, 3) or not all(parts):
            raise NotFound(f"'{ref}' names no earlier item or value")
        request_id, item_id, value_id = parts[0], parts[1], parts[2] if len(parts) == 3 else None
        record = self.requests.load(request_id)
        item = next((i for i in record.items if i.item_id == item_id and i.kind == "file"), None)
        if item is None:
            raise NotFound(f"request {request_id} has no file {item_id}")
        source = ItemRef(request_id, item_id)
        if value_id is None:
            return (source, item), None
        values = self.requests.load_result(request_id, item_id).get("values") or []
        record_of = next(
            (v for v in values if isinstance(v, dict) and v.get("id") == value_id), None
        )
        if record_of is None:
            raise NotFound(f"{item_id} of request {request_id} has no value {value_id}")
        return (source, item), EvidenceValue(value_id, record_of, source)

    def _answer_drawing(self, request_id: str, item_id: str) -> None:
        """Answer the message's question from the drawing's JSON, on the drawing's card."""
        record = self.requests.load(request_id)
        try:
            document = self.requests.load_result(request_id, item_id)
            answer = self.questions().drawing(
                record.text,
                [(ItemRef(request_id, item_id), document, False)],
                request_id,
                _earlier(self.requests, record),
            )
        except Exception as error:
            log.warning("answering %s of request %s failed: %s", item_id, request_id, error)
            with self._update(request_id, item_id) as item:
                item.status, item.reply = "done", f"{NOT_ANSWERED} {error}"
            return
        with self._update(request_id, item_id) as item:
            item.status, item.qa, item.reply = "done", answer, answer.reply

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


def _earlier(requests: RequestStorePort, record: RequestRecord) -> list[tuple[str, str]]:
    """The last turns of the conversation before this message: what was said, and replied."""
    turns = [
        (other.text, "\n".join(item.reply for item in other.items if item.reply))
        for other in reversed(requests.list(EARLIER_TURNS * 4, record.conversation_id))
        if other.created_at < record.created_at
    ]
    return turns[-EARLIER_TURNS:]


def _traced_text(text: str) -> dict[str, Any]:
    """The message text as the trace keeps it: its length and hash, never the words.

    The words live once, in the request record, which is the chat history.
    """
    return {"text_chars": len(text), "text_sha256": hashlib.sha256(text.encode()).hexdigest()}


def _free_id(taken: set[str], base: str) -> str:
    """`base`, or `base-2`, `base-3`... when a file of the message already has that id."""
    found, number = base, 1
    while found in taken:
        number += 1
        found = f"{base}-{number}"
    return found


def _is_drawing(item: RequestItem) -> bool:
    return item.kind == "file" and item.route is not None and item.route.route == Route.DRAWING


def _queued(item: RequestItem, decision: Routing) -> bool:
    """Whether the item waits for a job: a drawing to read, or a photo to answer."""
    return decision.route == Route.DRAWING or (
        decision.route == Route.PHOTO and item.kind == "file"
    )


def _fail(item: RequestItem, error: str) -> None:
    item.status, item.error, item.progress, item.finished_at = "failed", error, None, now()


def _shorten(text: str, limit: int = 80) -> str:
    line = " ".join(text.split())
    return line if len(line) <= limit else f"{line[: limit - 1]}…"
