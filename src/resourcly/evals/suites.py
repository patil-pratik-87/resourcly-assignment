"""One suite per component: how to load its gold cases, call it, and score what it returned."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from resourcly.bootstrap import Services
from resourcly.evals import metrics
from resourcly.evals.cases import Case, reader_cases


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
    # metrics that are better when they fall, such as a time; compare reads them that way
    lower_is_better: tuple[str, ...] = ()


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


def _feature_types(document: dict[str, Any]) -> dict[str, str]:
    features = document.get("features")
    return {
        f["id"]: f["type"]
        for f in (features if isinstance(features, list) else [])
        if isinstance(f, dict) and isinstance(f.get("id"), str) and isinstance(f.get("type"), str)
    }


def _reading(case: Case, prediction: Any) -> metrics.ReadingScore:
    return metrics.score_reading(
        case.gold["values"],
        scored_values(case, prediction),
        _feature_types(case.gold),
        _feature_types(_predicted_document(prediction)),
    )


def _score_reading(case: Case, prediction: Any) -> dict[str, Any]:
    score = _reading(case, prediction)
    return {
        "case_score": score.strict.f1 if case.stratum == "full" else score.strict.recall,
        "strict_f1": score.strict.f1,
        "strict_precision": score.strict.precision,
        "strict_recall": score.strict.recall,
        "strict_matched": score.strict.matched,
        "gold": score.strict.gold,
        "predicted": score.strict.predicted,
        "loose_matched": score.loose.matched,
        "kind_accuracy": score.kind_accuracy,
        "feature_accuracy": score.feature_accuracy,
        "feature_pairs": sum(score.feature_confusion.values()),
        "invalid_records": score.invalid,
        "schema_issues": len(prediction.get("issues", [])) if isinstance(prediction, dict) else 0,
        "pages": {
            str(page): [counts.gold, counts.predicted, counts.matched]
            for page, counts in score.pages.items()
        },
    }


def _summarise_readings(results: list[tuple[Case, Any]]) -> dict[str, Any]:
    summary = metrics.summarise_readings(
        [(case.stratum, _reading(case, prediction)) for case, prediction in results]
    )
    failures = sum(1 for _, prediction in results if not _schema_valid(prediction))
    return {**summary, "schema_failures": failures}


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


def _schema_valid(prediction: Any) -> bool:
    return isinstance(prediction, dict) and not prediction.get("issues")


SUITES: dict[str, Suite] = {
    "reader": Suite(
        component="reader",
        primary_metric="strict_f1",
        metrics=(
            "strict_f1",
            "strict_precision",
            "strict_recall",
            "loose_f1",
            "partial_recall",
            "kind_accuracy",
            "feature_accuracy",
        ),
        case_columns=("gold", "predicted", "strict_matched"),
        load=reader_cases,
        call=_read,
        score=_score_reading,
        summarise=_summarise_readings,
        explain=_explain_reading,
    ),
}
