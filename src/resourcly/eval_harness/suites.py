"""One suite per component: how to load its gold cases, call it, and score what it returned."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from resourcly.bootstrap import Services
from resourcly.eval_harness import metrics
from resourcly.eval_harness.cases import Case, failure_cases, reader_cases, route_cases


@dataclass(frozen=True)
class Suite:
    """A component's eval. Each case's scores carry a "case_score" that compare pairs by case."""

    component: str
    primary_metric: str
    metrics: tuple[str, ...]
    case_columns: tuple[str, ...]
    load: Callable[[Services, str], list[Case]]
    call: Callable[[Services, Case, str], Any]
    score: Callable[[Case, Any], dict[str, Any]]
    summarise: Callable[[list[tuple[Case, Any]]], dict[str, Any]]
    explain: Callable[[Case, Any], list[str]]


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


def _summarise_readings(results: list[tuple[Case, Any]]) -> dict[str, Any]:
    return metrics.summarise_readings(
        [(case.stratum, _reading(case, prediction)) for case, prediction in results]
    )


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
        lines.append(f"schema issues ({len(issues)})")
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


def _summarise_routes(results: list[tuple[Case, Any]]) -> dict[str, Any]:
    return metrics.summarise_routes(
        [
            metrics.RouteOutcome(
                case_id=case.case_id,
                expected=case.gold["expected_route"],
                route=_field(prediction, "route"),
                layer=_field(prediction, "layer"),
                reason=_field(prediction, "reason"),
            )
            for case, prediction in results
        ]
    )


def _find(services: Services, case: Case, request_id: str) -> Any:
    """Send the case's image to the failure finder of the version under test."""
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


def _summarise_failures(results: list[tuple[Case, Any]]) -> dict[str, Any]:
    return metrics.summarise_failures(
        [
            (case.stratum, metrics.score_failure(case.gold, _figures(prediction)))
            for case, prediction in results
        ]
    )


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


SUITES: dict[str, Suite] = {
    "reader": Suite(
        component="reader",
        primary_metric="f1",
        metrics=("f1", "precision", "recall", "partial_recall"),
        case_columns=("gold", "predicted", "matched"),
        load=reader_cases,
        call=_read,
        score=_score_reading,
        summarise=_summarise_readings,
        explain=_explain_reading,
    ),
    "router": Suite(
        component="router",
        primary_metric="accuracy",
        metrics=("accuracy", "drawing_recall", "other_kept_out"),
        case_columns=("route", "layer", "confidence"),
        load=route_cases,
        call=_route,
        score=_score_route,
        summarise=_summarise_routes,
        explain=_explain_route,
    ),
    "failure": Suite(
        component="failure",
        primary_metric="section@1",
        metrics=("section@1", "mode@3", "kept_out"),
        case_columns=("top",),
        load=failure_cases,
        call=_find,
        score=_score_failure,
        summarise=_summarise_failures,
        explain=_explain_failure,
    ),
}
