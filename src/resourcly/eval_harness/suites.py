"""One suite per component: how to load its gold cases, call it, and score what it returned."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from resourcly.bootstrap import Services
from resourcly.eval_harness import metrics
from resourcly.eval_harness.cases import failure_cases, reader_cases, route_cases
from resourcly.eval_harness.models import Case


@dataclass(frozen=True)
class Suite:
    """A component's eval. Each case's scores carry a "case_score" that compare pairs by case.

    The first metric is the primary one, the number that says better or worse. A run's summary
    is made from its cases' stored scores, with each case's stratum. A suite that is a second
    setting of a component, such as failure-copy, runs that component's versions.
    """

    component: str
    metrics: tuple[str, ...]
    case_columns: tuple[str, ...]  # scores `show` lists beside each case_score
    load: Callable[[Services, str], list[Case]]
    call: Callable[[Services, Case, str], Any]
    score: Callable[[Case, Any], dict[str, Any]]
    summarise: Callable[[metrics.Scored], dict[str, Any]]
    explain: Callable[[Case, Any], list[str]]
    setting_of: str | None = None

    @property
    def primary(self) -> str:
        return self.metrics[0]

    @property
    def part(self) -> str:
        """The component whose versions it runs: its own, or the one it is a setting of."""
        return self.setting_of or self.component


def _read(services: Services, case: Case, request_id: str) -> Any:
    return services.drawings.read(case.case_id, request_id=request_id).model_dump(mode="json")


def _predicted_values(prediction: Any) -> list[Any]:
    """The value records of a stored reading; a failed call or a malformed document gives none."""
    values = _predicted_document(prediction).get("values")
    return values if isinstance(values, list) else []


def scored_values(case: Case, prediction: Any) -> list[Any]:
    """The predicted records to score: those on the pages the gold covers, when it names them.

    A gold document with `page_coverage` is labelled in full on those pages only, so a prediction
    on another page is neither right nor wrong. A record whose page is not a number is kept, so it
    still counts as invalid.
    """
    values = _predicted_values(prediction)
    coverage = case.gold.get("page_coverage")
    if not coverage:
        return values
    return [
        r
        for r in values
        if not (isinstance(r, dict) and type(r.get("page")) is int) or r["page"] in coverage
    ]


def _predicted_document(prediction: Any) -> dict[str, Any]:
    document = prediction.get("document") if isinstance(prediction, dict) else None
    return document if isinstance(document, dict) else {}


def _reading(case: Case, prediction: Any) -> metrics.Counts:
    return metrics.score_reading(case.gold["values"], scored_values(case, prediction))


def _score_reading(case: Case, prediction: Any) -> dict[str, Any]:
    counts = _reading(case, prediction)
    return {
        "case_score": counts.f1 if case.stratum == "full" else counts.recall,
        "f1": counts.f1,
        "precision": counts.precision,
        "recall": counts.recall,
        "matched": counts.matched,
        "gold": counts.gold,
        "predicted": counts.predicted,
    }


def _explain_reading(case: Case, prediction: Any) -> list[str]:
    missed, extra = metrics.unmatched(case.gold["values"], scored_values(case, prediction))
    lines = [f"missed gold records ({len(missed)})", *(f"  {_record(r)}" for r in missed)]
    heading = (
        f"extra predictions ({len(extra)})"
        if case.stratum == "full"
        else f"predictions not in the partial gold ({len(extra)}); they may still be right"
    )
    lines += [heading, *(f"  {_record(r)}" for r in extra)]
    issues = prediction.get("issues", []) if isinstance(prediction, dict) else []
    if issues:
        lines.append(f"issues ({len(issues)})")
        lines += [
            f"  {'.'.join(map(str, i['loc'])) or '(document)'}: {i['message']}" for i in issues
        ]
    return lines


def _record(record: Any) -> str:
    if not isinstance(record, dict):
        return f"unreadable record {record!r}"
    value = "-" if record.get("value") is None else record.get("value")
    return (
        f"page {record.get('page')}  {record.get('kind')}  {record.get('raw')!r}"
        f"  value {value}  unit {record.get('unit') or '-'}"
    )


def _route(services: Services, case: Case, request_id: str) -> Any:
    """Send the case's request, its text and its file, to the router of the version under test."""
    request = case.gold["input"]
    attachment = services.gold.route_attachment(request["file"]) if request["file"] else None
    routing = services.router.route(request["text"], attachment, request_id=request_id)
    return routing.model_dump(mode="json")


def _field(prediction: Any, name: str) -> Any:
    return prediction.get(name) if isinstance(prediction, dict) else None


def _score_route(case: Case, prediction: Any) -> dict[str, Any]:
    correct = float(_field(prediction, "route") == case.gold["expected_route"])
    return {
        "case_score": correct,
        "correct": correct,
        "route": _field(prediction, "route"),
        "layer": _field(prediction, "layer"),
        "confidence": _field(prediction, "confidence"),
    }


def _explain_route(case: Case, prediction: Any) -> list[str]:
    got = _field(prediction, "route") or "nothing"
    lines = [f"expected {case.gold['expected_route']}, got {got}"]
    if isinstance(prediction, dict):
        lines.append(f"decided by the {prediction.get('layer')} layer: {prediction.get('reason')}")
        lines.append(f"probabilities {prediction.get('probabilities')}")
    lines.append(f"file {case.gold['input']['file'] or '(none)'}: {case.gold.get('notes') or ''}")
    return lines


def _hidden(case: Case) -> set[str]:
    """The figure a photo was made from, which the held-out setting hides from the search."""
    return {case.gold["expected_figure"]} if case.stratum == metrics.PHOTO else set()


def _find(services: Services, case: Case, request_id: str) -> Any:
    """Send the case's image to the failure finder of the version under test, held out: the
    photo's own figure is hidden, so the best hit must be another figure of its section."""
    photo = services.gold.failure_photo(case.gold["image"])
    found = services.failures.find(photo, request_id=request_id, exclude=_hidden(case))
    return found.model_dump(mode="json")


def _find_copy(services: Services, case: Case, request_id: str) -> Any:
    """Send the case's image to the finder with its own figure in the search: the copy setting."""
    photo = services.gold.failure_photo(case.gold["image"])
    return services.failures.find(photo, request_id=request_id).model_dump(mode="json")


def _figures(prediction: Any) -> list[Any] | None:
    """The ranked figures of a stored answer; None for a failed call or a malformed answer."""
    figures = _field(prediction, "figures")
    return figures if isinstance(figures, list) else None


def _score_failure(case: Case, prediction: Any) -> dict[str, Any]:
    scores = metrics.score_failure(case.gold, _figures(prediction))
    top = (_figures(prediction) or [None])[0]
    return {
        "case_score": scores["section@1" if case.stratum == "positive" else "kept_out"],
        **scores,
        "top": top.get("figure") if isinstance(top, dict) else None,
    }


def _explain_failure(case: Case, prediction: Any) -> list[str]:
    gold = case.gold
    if case.stratum == "positive":
        lines = [
            f"expected {gold['expected_figure']}: {gold['section']}, {gold['failure_mode']}",
        ]
    else:
        lines = [f"a negative ({case.stratum.removeprefix('negative_')}): expected no figure"]
    figures = _figures(prediction)
    if figures is None:
        return [*lines, "no answer"]
    lines.append(f"{len(figures)} figure(s) back; the first three:")
    lines += [
        f"  {f.get('figure')}  {f.get('section')}  {f.get('failure_mode')}  score {f.get('score')}"
        for f in figures[:3]
        if isinstance(f, dict)
    ]
    return lines


def _answer(services: Services, case: Case, request_id: str) -> Any:
    """Ask the photo answer of the version under test about the case's image, with no text, held
    out like the failure suite. The finder is the failure version the settings name."""
    photo = services.gold.failure_photo(case.gold["image"])
    answer = services.photo_answers.answer(photo, "", request_id, exclude=_hidden(case))
    return answer.model_dump(mode="json")


def _score_answer(case: Case, prediction: Any) -> dict[str, Any]:
    return metrics.score_answer(case.gold, prediction)


def _explain_answer(case: Case, prediction: Any) -> list[str]:
    gold = case.gold
    if case.stratum == metrics.PHOTO:
        keywords = ", ".join(gold["failure_keywords"])
        lines = [
            f"expected report {gold['expected_report']}, failure mode {gold['failure_mode']}"
            f" (keywords: {keywords})"
        ]
    else:
        lines = [f"a negative ({case.stratum.removeprefix('negative_')}): expected no match"]
    if not isinstance(prediction, dict):
        return [*lines, "no answer"]
    said = "not in the reports" if prediction.get("not_in_reports") else "matched"
    if not prediction.get("not_in_reports") and not prediction.get("matched"):
        said = "no match"
    lines.append(f"{said}: {prediction.get('answer')}")
    figures = [f for f in prediction.get("figures") or [] if isinstance(f, dict)]
    for item in [*(prediction.get("findings") or []), *(prediction.get("actions") or [])]:
        citation = item.get("citation") if isinstance(item, dict) else None
        if isinstance(citation, dict):
            valid = "valid" if metrics.valid_citation(citation, figures) else "invalid"
            text = item.get("statement") or item.get("action")
            lines.append(f"  [{citation.get('source')}] {valid}  {text}")
    lines.append(f"closest figures: {', '.join(str(f.get('figure')) for f in figures[:3])}")
    return lines


SUITES: dict[str, Suite] = {
    "reader": Suite(
        component="reader",
        metrics=("f1", "precision", "recall", "partial_recall"),
        case_columns=("gold", "predicted", "matched"),
        load=reader_cases,
        call=_read,
        score=_score_reading,
        summarise=metrics.summarise_readings,
        explain=_explain_reading,
    ),
    "router": Suite(
        component="router",
        metrics=("accuracy", "drawing_recall", "other_kept_out"),
        case_columns=("route", "layer", "confidence"),
        load=route_cases,
        call=_route,
        score=_score_route,
        summarise=metrics.summarise_routes,
        explain=_explain_route,
    ),
    "failure": Suite(
        component="failure",
        metrics=("section@1", "mode@3", "kept_out"),
        case_columns=("top",),
        load=failure_cases,
        call=_find,
        score=_score_failure,
        summarise=metrics.summarise_failures,
        explain=_explain_failure,
    ),
    "failure-copy": Suite(
        component="failure-copy",
        metrics=("section@1", "mode@3", "kept_out"),
        case_columns=("top",),
        load=failure_cases,
        call=_find_copy,
        score=_score_failure,
        summarise=metrics.summarise_failures,
        explain=_explain_failure,
        setting_of="failure",
    ),
    "answer": Suite(
        component="answer",
        metrics=("correct", "report_cited", "mode_named", "citations_valid", "kept_out"),
        case_columns=("matched", "report_cited", "mode_named"),
        load=failure_cases,
        call=_answer,
        score=_score_answer,
        summarise=metrics.summarise_answers,
        explain=_explain_answer,
    ),
}
