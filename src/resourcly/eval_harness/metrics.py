"""Pure scoring functions: records and labels in, numbers out. No files, models or network."""

import math
import re
import unicodedata
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

Record = dict[str, Any]

UNITS = {
    "mm": "mm",
    "millimeter": "mm",
    "millimeters": "mm",
    "millimetre": "mm",
    "millimetres": "mm",
    "in": "in",
    "inch": "in",
    "inches": "in",
    '"': "in",
    "deg": "deg",
    "degree": "deg",
    "degrees": "deg",
    "°": "deg",
}
UNIT_MARKS = str.maketrans({"º": "°", "˚": "°", "″": '"'})
SYMBOLS = str.maketrans({"ø": "⌀", "∅": "⌀", "−": "-", "–": "-", "\u2014": "-", "‐": "-"})


@dataclass(frozen=True)
class Counts:
    gold: int = 0
    predicted: int = 0
    matched: int = 0

    @property
    def precision(self) -> float:
        return self.matched / self.predicted if self.predicted else 0.0

    @property
    def recall(self) -> float:
        return self.matched / self.gold if self.gold else 0.0

    @property
    def f1(self) -> float:
        total = self.precision + self.recall
        return 2 * self.precision * self.recall / total if total else 0.0

    def __add__(self, other: "Counts") -> "Counts":
        return Counts(
            self.gold + other.gold,
            self.predicted + other.predicted,
            self.matched + other.matched,
        )


def score_reading(gold: list[Record], predicted: list[Record]) -> Counts:
    """Gold, predicted and matched records; a match needs the same page, unit, kind and value.

    A record with no number uses its normalised raw text in place of the value. A predicted record
    that cannot be read (no page, a value that is not a number) is invalid: it counts as a
    prediction and never matches.
    """
    gold_keys = Counter(_key(record) for record in gold)
    readable = [key for record in predicted if (key := _readable_key(record)) is not None]
    predicted_keys = Counter(readable)
    invalid = len(predicted) - len(readable)
    return Counts(
        gold_keys.total(),
        predicted_keys.total() + invalid,
        (gold_keys & predicted_keys).total(),
    )


def unmatched(gold: list[Record], predicted: list[Record]) -> tuple[list[Record], list[Record]]:
    """The gold records no prediction matched, and the predictions that matched none."""
    gold_keys = [_key(record) for record in gold]
    predicted_keys = [_readable_key(record) for record in predicted]
    budget = Counter(gold_keys) & Counter(key for key in predicted_keys if key is not None)
    return _leftover(gold, gold_keys, budget.copy()), _leftover(predicted, predicted_keys, budget)


def _leftover(records: list[Record], keys: list[tuple | None], budget: Counter) -> list[Record]:
    left = []
    for record, key in zip(records, keys, strict=True):
        if key is not None and budget[key] > 0:
            budget[key] -= 1
        else:
            left.append(record)
    return left


def normalise_raw(text: str) -> str:
    """Casefolded, one diameter sign, one minus sign and single spaces."""
    folded = unicodedata.normalize("NFKC", text).casefold().translate(SYMBOLS)
    return " ".join(folded.split())


def normalise_unit(unit: str | None) -> str | None:
    """A known unit as mm, in or deg. Marks OCR gives for degrees and inches are mapped first,
    because NFKC would turn the ordinal sign "º" into the letter "o"."""
    text = unicodedata.normalize("NFKC", (unit or "").translate(UNIT_MARKS))
    folded = text.strip().casefold().rstrip(".")
    if folded in ("", "none"):
        return None
    return UNITS.get(folded, folded)


def normalise_value(value: Any) -> tuple[float, ...] | None:
    """A number or [lower, upper] as rounded floats; numbers may arrive as text such as ".250"."""
    if value is None:
        return None
    items = value if isinstance(value, list | tuple) else [value]
    return tuple(_number(item) for item in items)


def _number(item: Any) -> float:
    """A finite number; a bool, NaN or infinity is refused, so the record is unreadable."""
    if isinstance(item, bool):
        raise TypeError("a bool is not a number")
    number = float(item)
    if not math.isfinite(number):
        raise ValueError(f"{item!r} is not a finite number")
    return round(number, 6)


def _kind(kind: Any) -> str:
    return re.sub(r"[\s-]+", "_", str(kind or "").strip().casefold())


def _readable_key(record: Any) -> tuple | None:
    try:
        key = _key(record)
    except (KeyError, TypeError, ValueError):
        return None
    page = key[0]
    return key if isinstance(page, int) and not isinstance(page, bool) else None


def _key(record: Record) -> tuple:
    value = normalise_value(record["value"])
    content = normalise_raw(record["raw"]) if value is None else value
    return record["page"], normalise_unit(record["unit"]), _kind(record["kind"]), content


Scored = list[tuple[str, dict[str, Any]]]  # each case's stratum and its stored scores


def summarise_readings(cases: Scored) -> dict[str, Any]:
    """Micro averages: F1, precision and recall over full drawings, recall only over partial gold.

    Partial gold lists a few values per drawing, so a prediction missing from it may still be right.
    A metric with no case to measure it on is None, not zero.
    """
    full = [_counts(scores) for stratum, scores in cases if stratum == "full"]
    partial = [_counts(scores) for stratum, scores in cases if stratum == "partial"]
    total = sum(full, Counts())
    return {
        "f1": total.f1 if full else None,
        "precision": total.precision if full else None,
        "recall": total.recall if full else None,
        "partial_recall": sum(partial, Counts()).recall if partial else None,
    }


def _counts(scores: dict[str, Any]) -> Counts:
    return Counts(scores["gold"], scores["predicted"], scores["matched"])


def summarise_routes(cases: Scored) -> dict[str, Any]:
    """How well a router picked the case; each case's stratum is the route it should get.

    Accuracy covers every request, the files that fit no case too, so a file let into the drawing
    or photo case lowers it. Drawing recall is the share of drawings sent to the reader. Other
    kept out is the share of the files that fit no case routed to other. A metric with nothing to
    measure is None.
    """
    return {
        "accuracy": _mean(cases, "correct", lambda stratum: True),
        "drawing_recall": _mean(cases, "correct", lambda stratum: stratum == "drawing"),
        "other_kept_out": _mean(cases, "correct", lambda stratum: stratum == "other"),
    }


PHOTO = "positive"


def score_failure(gold: dict[str, Any], figures: list[Any] | None) -> dict[str, float]:
    """How well the ranked figures answer one case; figures is None when the call failed.

    A photo of a report figure scores section@1 on whether the top figure is in the right report
    section, and mode@3 on whether one of the top three shows its failure mode. A negative, a photo
    no report covers, scores kept_out: 1 when no figure came back. A failed call keeps nothing out.
    """
    if gold["kind"] != PHOTO:
        return {"kept_out": float(figures == [])}
    ranked = [f for f in figures or [] if isinstance(f, dict)]
    top = ranked[0] if ranked else {}
    return {
        "section@1": float(
            (top.get("report"), top.get("section")) == (gold["expected_report"], gold["section"])
        ),
        "mode@3": float(any(f.get("failure_mode") == gold["failure_mode"] for f in ranked[:3])),
    }


def summarise_failures(cases: Scored) -> dict[str, Any]:
    """Means over the photos of report figures, and the share of negatives kept out."""
    return {
        "section@1": _mean(cases, "section@1", lambda stratum: stratum == PHOTO),
        "mode@3": _mean(cases, "mode@3", lambda stratum: stratum == PHOTO),
        "kept_out": _mean(cases, "kept_out", lambda stratum: stratum != PHOTO),
    }


def _mean(cases: Scored, name: str, keep: Callable[[str], bool]) -> float | None:
    """The mean of one score over the cases whose stratum `keep` accepts; None for no case."""
    values = [scores[name] for stratum, scores in cases if keep(stratum)]
    return sum(values) / len(values) if values else None


# Words of the answer prompts that a user should never read: the private name of a figure image,
# and the JSON fields an action's rule talks about
PROMPT_WORDS = re.compile(r"\breference images?\b|\bbasis\b|\bquote\b", re.I)


def score_answer(gold: dict[str, Any], answer: Any) -> dict[str, Any]:
    """How well one photo answer says what is wrong; answer is None when the call failed.

    A photo of a report figure is answered correctly when the answer is a match (the closest
    figures show the same failure), a citation is in its report, a word of the answer or its
    findings starts with one of its failure keywords, and every citation is valid. A negative is
    answered correctly when the answer says the reports say nothing about it: the gate found no
    figure close enough, or the model saw no part. An answer that only finds no match still
    shows the closest figures, so it does not keep a negative out. Any answer is prompt free when
    its text, findings and actions use none of the prompt's own words.
    """
    answer = answer if isinstance(answer, dict) else {}
    citations = _citations(answer)
    figures = [f for f in answer.get("figures") or [] if isinstance(f, dict)]
    counts = {
        "matched": answer.get("matched"),
        "citations": len(citations),
        "valid_citations": sum(valid_citation(c, figures) for c in citations),
    }
    shown = " ".join(
        [
            str(answer.get("answer") or ""),
            *(str(f.get("statement")) for f in _findings(answer)),
            *(str(a.get("action")) for a in answer.get("actions") or [] if isinstance(a, dict)),
        ]
    )
    prompt_free = float(PROMPT_WORDS.search(shown) is None)
    if gold["kind"] != PHOTO:
        kept_out = float(answer.get("not_in_reports") is True)
        return {
            "case_score": kept_out,
            "correct": kept_out,
            "kept_out": kept_out,
            **counts,
            "prompt_free": prompt_free,
        }
    report_cited = float(any(c.get("report") == gold["expected_report"] for c in citations))
    text = " ".join(
        [str(answer.get("answer") or ""), *(str(f.get("statement")) for f in _findings(answer))]
    )
    mode_named = float(
        any(re.search(rf"\b{re.escape(word)}", text, re.I) for word in gold["failure_keywords"])
    )
    correct = float(
        answer.get("matched") is True
        and bool(report_cited and mode_named)
        and counts["valid_citations"] == counts["citations"]
    )
    return {
        "case_score": correct,
        "correct": correct,
        "matched": counts["matched"],
        "report_cited": report_cited,
        "mode_named": mode_named,
        "citations": counts["citations"],
        "valid_citations": counts["valid_citations"],
        "prompt_free": prompt_free,
    }


def _findings(answer: dict[str, Any]) -> list[dict[str, Any]]:
    return [f for f in answer.get("findings") or [] if isinstance(f, dict)]


def _citations(answer: dict[str, Any]) -> list[dict[str, Any]]:
    """Every citation of the answer's findings and actions; a stated action's carries its basis
    and quote, which `valid_citation` checks."""
    findings = [f.get("citation") for f in _findings(answer)]
    actions = [
        {**a["citation"], "basis": a.get("basis"), "quote": a.get("quote")}
        for a in answer.get("actions") or []
        if isinstance(a, dict) and isinstance(a.get("citation"), dict)
    ]
    return [c for c in [*findings, *actions] if isinstance(c, dict)]


MIN_QUOTE_WORDS = 3  # as the app requires of a stated action's quote


def valid_citation(citation: dict[str, Any], figures: list[dict[str, Any]]) -> bool:
    """A citation names a figure the finder returned, or a page of one of their reports, and its
    source says the same report and figure or page. A stated action must cite a page and quote
    at least three of its words; the page's text is not stored, so the words are not checked."""
    report, page, figure = citation.get("report"), citation.get("page"), citation.get("figure")
    if citation.get("basis") == "stated" and (
        figure is not None or len(str(citation.get("quote") or "").split()) < MIN_QUOTE_WORDS
    ):
        return False
    if figure is None:
        return (
            report in {f.get("report") for f in figures}
            and type(page) is int
            and citation.get("source") == f"{report} p{page}"
        )
    return (
        figure in {f.get("figure") for f in figures}
        and str(figure).split("/")[0] == report
        and citation.get("source") == str(figure).replace("/", " ")
    )


def summarise_answers(cases: Scored) -> dict[str, Any]:
    """The share of every case answered correctly first, then the parts of a photo's answer, the
    share of valid citations over every case, the share of negatives kept out, and the share of
    every case whose answer is prompt free."""
    citations = sum(scores["citations"] for _, scores in cases)
    valid = sum(scores["valid_citations"] for _, scores in cases)
    return {
        "correct": _mean(cases, "correct", lambda stratum: True),
        "report_cited": _mean(cases, "report_cited", lambda stratum: stratum == PHOTO),
        "mode_named": _mean(cases, "mode_named", lambda stratum: stratum == PHOTO),
        "citations_valid": valid / citations if citations else None,
        "kept_out": _mean(cases, "kept_out", lambda stratum: stratum != PHOTO),
        "prompt_free": _mean(cases, "prompt_free", lambda stratum: True),
    }


# How one answer to a question scores: right, the right value among candidates to tap, no answer,
# or a wrong answer shown, which is worse than none.
RIGHT, AMONG_CANDIDATES, NO_ANSWER, WRONG_SHOWN = 1.0, 0.5, 0.0, -1.0
QA_STRATA = ("drawing", "place", "photo", "text", "none")


def question_route(gold: dict[str, Any]) -> str:
    """The route a question case goes to: drawing, text or photo."""
    if gold["kind"] == "none":
        return gold["route"]
    return {"drawing": "drawing", "place": "drawing"}.get(gold["kind"], gold["kind"])


def score_question(gold: dict[str, Any], prediction: Any) -> dict[str, Any]:
    """How well one answer answers its question; prediction is None when the call failed.

    A drawing answer is right when the value it shows has the expected number and unit (or, for
    words such as a title block line, the expected text); candidates score 0.5 when the right
    value is among them. A text answer is right when it cites a gold page. A photo answer is right
    when it matches and the first figure it cites (or its top figure, when it cites none) is in the
    expected section, or in the expected report with the expected failure mode, as section@1 asks
    of the finder; citing more figures earns nothing. An unanswerable
    question is right when nothing is answered. A wrong value, page or figure shown scores -1.
    """
    answer = prediction if isinstance(prediction, dict) else {}
    route = question_route(gold)
    if route == "photo":
        score = _photo_score(gold, answer)
        cites = [c.get("source") for c in _citations(answer)]
        valid = sum(valid_citation(c, _photo_figures(answer)) for c in _citations(answer))
        dropped = len(cites) - valid
    else:
        score = (_drawing_score if route == "drawing" else _text_score)(gold, answer)
        valid = len(answer.get("cites") or [])
        dropped = len(answer.get("dropped") or [])
    return {
        "case_score": score,
        "outcome": _outcome(answer, route),
        "wrong": float(score == WRONG_SHOWN),
        "valid_cites": valid,
        "dropped_cites": dropped,
    }


def _outcome(answer: dict[str, Any], route: str) -> str | None:
    if route != "photo":
        return answer.get("outcome")
    if not answer:
        return None
    return "answer" if answer.get("matched") is True else "none"


def _drawing_score(gold: dict[str, Any], answer: dict[str, Any]) -> float:
    outcome = answer.get("outcome")
    shown = [r for r in answer.get("shown_values") or [] if isinstance(r, dict)]
    if gold["kind"] == "none":
        return {"none": RIGHT, "answer": WRONG_SHOWN}.get(outcome, NO_ANSWER)
    if outcome == "answer" and shown:
        return RIGHT if _expected(gold, shown[0]) else WRONG_SHOWN
    if outcome == "candidates" and any(_expected(gold, record) for record in shown):
        return AMONG_CANDIDATES
    return NO_ANSWER


def _expected(gold: dict[str, Any], record: dict[str, Any]) -> bool:
    """Whether a shown record is one the gold expects: its number and unit, or its text."""
    for expected in gold["expected"]:
        if "raw" in expected:
            if normalise_raw(str(record.get("raw") or "")) == normalise_raw(expected["raw"]):
                return True
        elif normalise_value(record.get("value")) == normalise_value(
            expected["value"]
        ) and normalise_unit(record.get("unit")) == normalise_unit(expected["unit"]):
            return True
    return False


def _text_score(gold: dict[str, Any], answer: dict[str, Any]) -> float:
    outcome = answer.get("outcome")
    if gold["kind"] == "none":
        return {"none": RIGHT, "answer": WRONG_SHOWN}.get(outcome, NO_ANSWER)
    if outcome != "answer":
        return NO_ANSWER
    cited = {c.get("ref") for c in answer.get("citations") or [] if isinstance(c, dict)}
    return RIGHT if cited & set(gold["pages"]) else WRONG_SHOWN


def _photo_figures(answer: dict[str, Any]) -> list[dict[str, Any]]:
    return [f for f in answer.get("figures") or [] if isinstance(f, dict)]


def _photo_score(gold: dict[str, Any], answer: dict[str, Any]) -> float:
    matched = answer.get("matched") is True and answer.get("not_in_reports") is not True
    if gold["kind"] == "none":
        return WRONG_SHOWN if matched else (RIGHT if answer else NO_ANSWER)
    if not matched:
        return NO_ANSWER
    figures = {f.get("figure"): f for f in _photo_figures(answer)}
    cited = [figures[c["figure"]] for c in _citations(answer) if c.get("figure") in figures]
    first = (cited or list(figures.values()) or [{}])[0]
    right = (first.get("report"), first.get("section")) == (
        gold["expected_report"],
        gold["section"],
    ) or (first.get("report"), first.get("failure_mode")) == (
        gold["expected_report"],
        gold["failure_mode"],
    )
    return RIGHT if right else WRONG_SHOWN


def summarise_questions(cases: Scored) -> dict[str, Any]:
    """The mean case score first, the share of cases that showed a wrong answer, the share of the
    model's citations that named its evidence, then the mean score of each kind of question."""
    valid = sum(scores["valid_cites"] for _, scores in cases)
    cited = valid + sum(scores["dropped_cites"] for _, scores in cases)
    return {
        "answer_score": _mean(cases, "case_score", lambda stratum: True),
        "wrong_shown": _mean(cases, "wrong", lambda stratum: True),
        "citations_valid": valid / cited if cited else None,
        **{
            stratum: _mean(cases, "case_score", lambda found, wanted=stratum: found == wanted)
            for stratum in QA_STRATA
        },
    }


AGENT_STRATA = ("text", "photo", "drawing", "picture", "other", "many", "follow-up")


def score_agent(gold: dict[str, Any], prediction: Any) -> dict[str, Any]:
    """How the agent handled the last turn of one conversation; prediction is None on a crash.

    Each item the gold lists must get its route, and an answer exactly when the gold gives one,
    on its own card; a message card no item lists is wrong. Each answer scores as a qa answer.
    The conversation is fully right when every route and card is right and every answer scores
    1. A drawing's JSON is scored against its gold as the reader suite scores it, apart.
    """
    found = prediction if isinstance(prediction, dict) else {}
    requests = [r for r in found.get("requests") or [] if isinstance(r, dict)]
    results = found.get("results") or {}
    last = requests[-1] if requests else {"request_id": "", "items": []}
    items = {item["item_id"]: item for item in last["items"]}
    listed = {spec["item"] for spec in gold["items"]}
    notes: list[str] = []
    routes, answers, counts = [], [], Counts()
    cards = bool(requests) and all(
        item["kind"] == "file" or item["item_id"] in listed for item in items.values()
    )
    if requests and not cards:
        notes.append("a message card the gold does not list")
    for spec in gold["items"]:
        item = items.get(spec["item"]) or {}
        route = (item.get("route") or {}).get("route")
        routes.append(float(route == spec["route"]))
        answered = bool(item.get("qa") or item.get("answer"))
        if answered != (spec["answer"] is not None):
            cards = False
            notes.append(f"{spec['item']}: {'an answer' if answered else 'no answer'} on its card")
        if spec["answer"] is not None:
            answers.append(
                score_question(spec["answer"], _agent_answer(item, results))["case_score"]
            )
            notes.append(f"{spec['item']}: route {route}, answer score {answers[-1]}")
        if spec.get("gold_values") is not None:
            read = results.get(f"{last['request_id']}/{spec['item']}")
            counts += score_reading(spec["gold_values"], read if isinstance(read, list) else [])
    route_ok = bool(routes) and all(routes)
    right = route_ok and cards and all(score == RIGHT for score in answers)
    return {
        "case_score": float(right),
        "routes": sum(routes) / len(routes) if routes else 0.0,
        "cards": float(cards),
        "answer_score": sum(answers) / len(answers) if answers else None,
        "gold": counts.gold,
        "predicted": counts.predicted,
        "matched": counts.matched,
        "notes": notes,
    }


def _agent_answer(item: dict[str, Any], results: dict[str, Any]) -> dict[str, Any] | None:
    """An item's answer as the qa suite stores one: a question's with the records it showed, or
    a photo's."""
    qa = item.get("qa")
    if not isinstance(qa, dict):
        return item.get("answer")
    shown = []
    for cited in [*(qa.get("citations") or []), *(qa.get("candidates") or [])]:
        values = results.get(f"{cited.get('request_id')}/{cited.get('item_id')}") or []
        shown += [v for v in values if isinstance(v, dict) and v.get("id") == cited.get("ref")]
    return {**qa, "shown_values": shown}


def summarise_agent(cases: Scored) -> dict[str, Any]:
    """The share of conversations fully right first; then routes, cards and answers, the JSON's
    micro F1 over the drawings with gold, and the share fully right of each kind of message."""
    json_counts = sum((_counts(scores) for _, scores in cases), Counts())
    answered = [s["answer_score"] for _, s in cases if s["answer_score"] is not None]
    return {
        "fully_right": _mean(cases, "case_score", lambda stratum: True),
        "routes": _mean(cases, "routes", lambda stratum: True),
        "cards": _mean(cases, "cards", lambda stratum: True),
        "answer_score": sum(answered) / len(answered) if answered else None,
        "json_f1": json_counts.f1 if json_counts.gold else None,
        **{
            stratum: _mean(cases, "case_score", lambda found, wanted=stratum: found == wanted)
            for stratum in AGENT_STRATA
        },
    }
