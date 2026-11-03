"""Answering a user's question about drawings or the NTSB reports. The model selects; code answers.

The route picks the evidence. For drawings it is the values of their stored JSON; the answerer
picks the values that answer and names the kind of value asked about, and code decides what to
show: one value of that kind is the answer, several are candidates for the user to tap, and none
is "Not on this drawing". When the question names a frame symbol, every frame is offered too, in
case the reader misread one. Every number shown is printed from a stored record, never from the
model's words. For the reports, the evidence is the passages a search finds; the answerer writes
statements that each cite a passage, and code keeps only those whose source it was shown.

Each step is traced under the request id with counts, ids and a hash of the question, never its
words.
"""

import hashlib
import logging
import re
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Literal

from resourcly.models import (
    Characteristic,
    Cited,
    DimensionKind,
    EvidenceValue,
    ItemRef,
    Passage,
    QuestionAnswer,
    SelectEvidence,
    TextEvidence,
    TraceEvent,
)
from resourcly.ports import QuestionAnswererPort, ReportSearchPort, TracePort
from resourcly.services import now

log = logging.getLogger(__name__)

FRAME_KINDS: tuple[str, ...] = Characteristic.__args__
# Kinds whose records hold words, not numbers: the answer is the record the answerer cites.
TEXT_KINDS = ("title_block", "note")
# Every kind a question may ask about, as the answerer names it; "none" for a question none fits.
KINDS: tuple[str, ...] = (
    *FRAME_KINDS,
    *DimensionKind.__args__,
    "datum_feature",
    "datum_target",
    "surface_texture",
    "thread",
    *TEXT_KINDS,
    "none",
)
# The kind a question asks about from its words, when the answerer names none. The first match
# wins, so a narrower phrase comes before a wider one.
KIND_WORDS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (kind, re.compile(pattern, re.I))
    for kind, pattern in (
        ("total_runout", r"\btotal run-?out"),
        ("circular_runout", r"\brun-?out"),
        ("profile_of_a_line", r"\bprofile of a line|\bline profile"),
        ("profile_of_a_surface", r"\bprofile"),
        ("perpendicularity", r"\bperpendicular"),
        ("parallelism", r"\bparallel"),
        ("flatness", r"\bflat(ness)?\b"),
        ("straightness", r"\bstraight(ness)?\b"),
        ("circularity", r"\bcircularity|\broundness"),
        ("cylindricity", r"\bcylindricity"),
        ("angularity", r"\bangularity"),
        ("concentricity", r"\bconcentric"),
        ("symmetry", r"\bsymmetr"),
        ("position", r"\bposition"),
        ("surface_texture", r"\bsurface (finish|texture)|\broughness"),
        ("thread", r"\bthread"),
        ("datum_feature", r"\bdatum"),
        ("title_block", r"\brevision|\brev\b|\btitle\b|\bdrawing number"),
        ("note", r"\bnotes?\b|\bmaterial|\bunits?\b|\bstandards?\b"),
        ("radius", r"\bradius|\bradii|\bfillet|\brounded corner"),
        ("angular", r"\bangle|\bdegrees?\b"),
        ("diameter", r"\bdiameter|\bholes?\b|\bbore|⌀"),
        ("linear", r"\blength|\bwidth|\bheight|\bthickness|\bdistance|\bdepth"),
    )
)
NOT_ON_DRAWING = "Not on this drawing."
NOT_IN_REPORTS = "The three NTSB reports do not say."
PICTURE = "These values were read from a picture of the drawing, so their boxes are not exact."
TURN_CHARS = 400  # each earlier turn is cut to this many characters in the prompt
WHOLE_PAGE = (0, 0, 1, 1)  # the box of a value read from a whole page, which has no box of its own


def words_kind(question: str) -> str | None:
    """The kind of value a question asks about, from a fixed word list; None when none fits."""
    return next((kind for kind, words in KIND_WORDS if words.search(question)), None)


def asked_kind(named: str | None, question: str) -> str | None:
    """The kind the answerer named when it is one, else the kind the word list finds."""
    kind = (named or "").strip().lower().replace(" ", "_")
    return kind if kind in KINDS and kind != "none" else words_kind(question)


def drawing_evidence(
    documents: Sequence[tuple[ItemRef, dict[str, Any], bool]], question: str, limit: int
) -> list[EvidenceValue]:
    """The values of the drawings, at most `limit`, those of the kind the question names first.

    Each document comes with the item it is from and whether it was read from a picture; a value
    whose box is the whole page was read from one too, as a page with no vector callouts is. A key
    is the value's id, or `<item id>:<id>` when another drawing has the same id.
    """
    values = [
        (source, record, picture)
        for source, document, picture in documents
        for record in document.get("values") or []
        if isinstance(record, dict) and record.get("id")
    ]
    counts: dict[str, int] = {}
    for _, record, _ in values:
        counts[record["id"]] = counts.get(record["id"], 0) + 1
    found = [
        EvidenceValue(
            key=record["id"] if counts[record["id"]] == 1 else f"{source.item_id}:{record['id']}",
            record=record,
            source=source,
            picture=picture or record.get("bbox") == list(WHOLE_PAGE),
        )
        for source, record, picture in values
    ]
    kind = words_kind(question)
    return sorted(found, key=lambda value: value.record.get("kind") != kind)[:limit]


@dataclass(frozen=True)
class Decision:
    """What code shows for a drawing question: an answer, candidates, or none.

    `frames` says none was found and every frame is offered in case one was misread.
    """

    outcome: Literal["answer", "candidates", "none"]
    shown: list[EvidenceValue] = field(default_factory=list)
    frames: bool = False


def decide(kind: str | None, cites: list[str], evidence: list[EvidenceValue]) -> Decision:
    """One value of the kind asked is the answer, several are candidates, the cited ones first.

    A title block or note answer is the record the answerer cites. With no value of a frame kind,
    the answer is none and every frame is offered.
    """
    cited = [value for value in evidence if value.key in cites]
    if kind in TEXT_KINDS:
        picked = [value for value in cited if value.record.get("kind") == kind] or cited
        return _of(picked)
    same = [value for value in evidence if kind and value.record.get("kind") == kind]
    if same:
        return _of(sorted(same, key=lambda value: value.key not in cites))
    if kind in FRAME_KINDS:
        frames = [v for v in evidence if v.record.get("callout") == "feature_control_frame"]
        return Decision("none", frames, frames=bool(frames))
    return Decision("none", [])


def _of(values: list[EvidenceValue]) -> Decision:
    if not values:
        return Decision("none", [])
    return Decision("answer" if len(values) == 1 else "candidates", values)


def cited_value(value: EvidenceValue) -> Cited:
    record = value.record
    bbox = record.get("bbox")
    return Cited(
        kind="value",
        ref=str(record["id"]),
        request_id=value.source.request_id,
        item_id=value.source.item_id,
        page=record.get("page") if type(record.get("page")) is int else None,
        bbox=tuple(bbox) if _is_box(bbox) and not value.picture else None,
        quote=str(record.get("raw") or ""),
        said=str(record["meaning"]) if record.get("meaning") else None,
    )


def _is_box(bbox: Any) -> bool:
    return (
        isinstance(bbox, list | tuple)
        and len(bbox) == 4
        and all(isinstance(n, int | float) for n in bbox)
    )


def render_drawing(decision: Decision, kind: str | None, picture: bool) -> str:
    """The reply, printed from the shown records."""
    shown = decision.shown
    if decision.outcome == "answer":
        lines = [_line(shown[0])]
    elif decision.outcome == "candidates":
        lines = [
            f"{len(shown)} values on the drawing could be the {_kind_words(kind)}."
            " Tap the one you mean.",
            *(f"- {_line(value)}" for value in shown),
        ]
    elif decision.frames:
        lines = [
            f"{NOT_ON_DRAWING} No {_kind_words(kind)} was read. The reader may have misread a"
            f" frame's symbol, so all {len(shown)} frames are shown."
        ]
    else:
        lines = [NOT_ON_DRAWING]
    if picture and shown:
        lines.append(PICTURE)
    return "\n".join(lines)


def _line(value: EvidenceValue) -> str:
    record = value.record
    page = f", page {record['page']}" if record.get("page") else ""
    meaning = f" {record['meaning']}" if record.get("meaning") else ""
    return f"{record.get('raw')} ({value.key}{page}).{meaning}"


def _kind_words(kind: str | None) -> str:
    return (kind or "value").replace("_", " ")


def earlier_block(earlier: Sequence[tuple[str, str]]) -> str:
    """The earlier turns of the conversation, each side cut to TURN_CHARS characters."""
    turns = [f"User: {_cut(said)}\nAgent: {_cut(reply)}" for said, reply in earlier]
    return "\n".join(turns) if turns else "(none)"


def blocks(evidence: str, earlier: Sequence[tuple[str, str]], question: str) -> str:
    """The prompt's marked blocks: the evidence, the earlier turns and the question."""
    return (
        f"<evidence>\n{evidence}\n</evidence>\n"
        f"<earlier_turns>\n{earlier_block(earlier)}\n</earlier_turns>\n"
        f"<question>\n{question.strip()}\n</question>"
    )


def value_lines(values: list[EvidenceValue]) -> str:
    return "\n".join(
        f"{value.key} {value.record.get('raw')} ({value.record.get('callout')},"
        f" {value.record.get('kind')}; page {value.record.get('page')})"
        for value in values
    )


def passage_lines(passages: list[Passage]) -> str:
    return "\n".join(f"[{passage.source}] {passage.text}" for passage in passages)


def _cut(text: str) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= TURN_CHARS else f"{flat[: TURN_CHARS - 1]}…"


# A page as an answer writes it: "16-006 p4", "[16-006 page 4]"
PAGE = re.compile(r"(\d{2}-\d{3})\W*p(?:age)?\.?\s*(\d+)", re.I)


class QuestionService:
    def __init__(
        self,
        answerer: QuestionAnswererPort,
        search: ReportSearchPort,
        trace: TracePort,
        qa_name: str,
        max_values: int = 60,
        passages: int = 6,
    ):
        self.answerer = answerer
        self.search = search
        self.trace = trace
        self.qa_name = qa_name
        self.max_values = max_values  # the values of the drawings the answerer is shown
        self.passages = passages  # the report passages a text answer is shown

    def needs_answer(self, text: str, request_id: str) -> bool:
        """Whether a message sent with files asks for more than reading them."""
        with self._step(request_id, "answer.gate", self.answerer.called) as step:
            step["input"] = traced_text(text)
            probability = self.answerer.gate(text)
            step["output"] = {
                "probability": round(probability, 3),
                "needs_answer": probability >= 0.5,
            }
        return probability >= 0.5

    def value(
        self, question: str, picked: Sequence[EvidenceValue], request_id: str
    ) -> QuestionAnswer:
        """Answer with the values the user picked, printed from their records; no model call."""
        with self._step(request_id, "answer.check", "code: the values the user picked") as step:
            step["input"] = {"values": [value.key for value in picked], **traced_text(question)}
            decision = _of(list(picked))
            picture = any(value.picture for value in picked)
            shown = [cited_value(value) for value in picked]
            kind = picked[0].record.get("kind") if len(picked) == 1 else None
            answer = QuestionAnswer(
                route="value",
                outcome=decision.outcome,
                reply=render_drawing(decision, kind, picture),
                kind=kind,
                citations=shown if decision.outcome == "answer" else [],
                candidates=shown if decision.outcome != "answer" else [],
                picture=picture,
            )
            step["output"] = {"outcome": answer.outcome, "shown": [c.ref for c in shown]}
        return answer

    def drawing(
        self,
        question: str,
        documents: Sequence[tuple[ItemRef, dict[str, Any], bool]],
        request_id: str,
        earlier: Sequence[tuple[str, str]] = (),
    ) -> QuestionAnswer:
        """Answer from the values of read drawings, each with its item and whether it was read
        from a picture."""
        values = drawing_evidence(documents, question, self.max_values)
        with self._step(request_id, "answer.select", self.answerer.called) as step:
            step["input"] = {
                "values": len(values),
                "earlier_turns": len(earlier),
                **traced_text(question),
            }
            prompt = blocks(value_lines(values), earlier, question)
            selection = self.answerer.select(SelectEvidence(question, values, prompt))
            keys = {value.key for value in values}
            cites = [key for key in selection.cites if key in keys]
            dropped = [key for key in selection.cites if key not in keys]
            step["output"] = {"kind": selection.kind, "cites": cites, "dropped": dropped}
        with self._step(
            request_id, "answer.check", "code: the kind asked, then the records"
        ) as step:
            kind = asked_kind(selection.kind, question)
            decision = decide(kind, cites, values)
            picture = any(value.picture for value in decision.shown)
            shown = [cited_value(value) for value in decision.shown]
            answer = QuestionAnswer(
                route="drawing",
                outcome=decision.outcome,
                reply=render_drawing(decision, kind, picture),
                kind=kind,
                citations=shown if decision.outcome == "answer" else [],
                candidates=shown if decision.outcome != "answer" else [],
                cites=cites,
                dropped=dropped,
                picture=picture,
            )
            step["input"] = {"kind": kind, "cites": cites}
            step["output"] = {"outcome": answer.outcome, "shown": [c.ref for c in shown]}
        return answer

    def text(
        self, question: str, request_id: str, earlier: Sequence[tuple[str, str]] = ()
    ) -> QuestionAnswer:
        """Answer from the report passages a search finds for the question and the turn before."""
        query = " ".join([question.strip(), *(said for said, _ in earlier[-1:])])
        passages = self.search.search(query, self.passages)
        with self._step(request_id, "answer.write", self.answerer.called) as step:
            step["input"] = {
                "passages": [passage.source for passage in passages],
                "earlier_turns": len(earlier),
                **traced_text(question),
            }
            prompt = blocks(passage_lines(passages), earlier, question)
            draft = self.answerer.write(TextEvidence(question, passages, prompt))
            step["output"] = {
                "not_in_reports": draft.not_in_reports,
                "statements": len(draft.statements),
            }
        with self._step(request_id, "answer.check", "code: each statement's source") as step:
            shown = {passage.source: passage for passage in passages}
            kept, dropped = [], []
            for statement in draft.statements:
                source = _page(statement.source)
                if source in shown:
                    kept.append((_sentence(statement.statement), shown[source]))
                else:
                    dropped.append(statement.source)
            answer = _text_answer(draft.answer, kept, dropped, draft.not_in_reports)
            answer.cites = [passage.source for _, passage in kept]
            step["output"] = {
                "outcome": answer.outcome,
                "cited": [c.ref for c in answer.citations],
                "dropped": dropped,
            }
        return answer

    @contextmanager
    def _step(self, request_id: str, step: str, called: str) -> Iterator[dict[str, Any]]:
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
                called=f"qa {self.qa_name}: {called}",
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


def _sentence(text: str) -> str:
    """A statement as a sentence: a model that copies a passage from mid-sentence starts it in
    lower case."""
    text = text.strip()
    return text[:1].upper() + text[1:]


def _page(source: str) -> str | None:
    found = PAGE.search(source)
    return f"{found[1]} p{int(found[2])}" if found else None


def _text_answer(
    answer: str,
    kept: list[tuple[str, Passage]],
    dropped: list[str],
    not_in_reports: bool,
) -> QuestionAnswer:
    if not_in_reports or not kept:
        return QuestionAnswer(route="text", outcome="none", reply=NOT_IN_REPORTS, dropped=dropped)
    citations = [
        Cited(kind="passage", ref=passage.source, page=passage.page, quote=passage.text, said=said)
        for said, passage in kept
    ]
    lines = [answer.strip() or kept[0][0], ""]
    lines += [f"- {statement} [{passage.source}]" for statement, passage in kept]
    return QuestionAnswer(
        route="text",
        outcome="answer",
        reply="\n".join(lines),
        citations=citations,
        dropped=dropped,
    )


def traced_text(text: str) -> dict[str, Any]:
    """The user's words as a trace keeps them: their length and hash, never the words."""
    return {
        "question_chars": len(text),
        "question_sha256": hashlib.sha256(text.encode()).hexdigest(),
    }
