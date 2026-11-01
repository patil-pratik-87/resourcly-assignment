# The eval harness

The `resourcly.evals` package scores any version of a component on its gold cases and says
whether a new version got better or worse. Every component has one shape: gold cases, a version
file, a score per case, a stored run and a comparison. The harness reaches the app only through
`open_services()` in `bootstrap.py`, so it measures the code the app runs.

```sh
uv run evals check                                   # every gold file and split
uv run evals run router --version stub-v0            # dev split by default
uv run evals show RUN_ID --case CASE_ID              # one case against its gold
uv run evals compare failure shuffled-v0 my-finder-v1 --fail-if-worse
uv run evals show --request REQUEST_ID               # what one call did
```

## Components

| Component | Gold | Primary metric | Other metrics | Versions |
| --- | --- | --- | --- | --- |
| `reader`: drawing to JSON | `evals/gold/drawings/`, `partial/` | `strict_f1` | `loose_f1`, `partial_recall`, `kind_accuracy`, `feature_accuracy` | `textlayer-v0` |
| `router`: which case a request is | `evals/gold/routes/` | `accuracy` | recall per route, `other_kept_out`, `escalation_rate`, `median_ms` | `stub-v0` |
| `failure`: photo to report figure | `evals/gold/failure/` | `section@1` | `report@1`, `mode@3`, `kept_out` | `shuffled-v0` |

- Reader: a value matches on page, unit, kind and number. Partial gold gives recall only.
- Router: accuracy covers drawing, photo and text requests. Files that fit no case are scored
  apart, as the share kept out. Escalation is the share decided by a vision-language model.
- Failure: section@1 asks whether the top figure is in the right report section, mode@3 whether
  one of the top three shows the right failure mode. Drawings and unrelated images should get no
  figure (`kept_out`).

## How a run works

A run loads the split's gold cases (`evals/splits.toml`) and calls the version on each one with
request id `<run id>:<case id>`, which leaves a trace. It stores each raw answer, error, time and
score in `runs/evals.sqlite`, with the version hash, the git commit and a hash of the cases and
their gold. A failed call is scored as an empty answer. `evals run --rescore RUN_ID` scores
stored answers against corrected gold without calling the component.

Splits keep related cases, such as a figure and its perturbed copies, on one side. Tune on dev.

## Comparing versions

`evals compare` takes run ids or version names. It gives a verdict per metric only when both runs
saw the same cases and gold, then lists each case by its change in `case_score`.

## Adding a component or a version

A version is a TOML file whose `impl` names an entry of `READERS`, `ROUTERS` or `FINDERS` in
`bootstrap.py`, and whose other keys are settings that entry lists. A new implementation is an
adapter of the component's port, registered there. A new component is one more `Suite` in
`src/resourcly/evals/suites.py`, with its gold loader in `cases.py` and its metrics in
`metrics.py`; the harness, the run store and `compare` need no change.
