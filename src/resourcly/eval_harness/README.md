# Eval harness

The eval harness tests each part of the agent on its own. Plug in a version of a part, run it on
chosen gold cases, and see whether it got better or worse than another version. Commands and
current numbers: [docs/evals.md](../../../docs/evals.md).

```text
gold cases + split -> version file -> call through open_services() -> score per case
                                                                          |
                          compare <- stored run (answers and scores) <----+
```

## Concepts

| Concept | What it is |
| --- | --- |
| Component | The part of the agent under test: `reader`, `router` or `failure`. |
| Gold case | An input and its known answer, in `evals/gold/`; partial gold gives recall only. |
| Split | Which cases are dev and which test, in `evals/splits.toml`. Related cases stay together. |
| Version file | `versions/<component>/<name>.toml`: an implementation and its settings. |
| Implementation | Code behind the component's port, registered as `impl` in `bootstrap.py`. |
| Run | One version on one split, with its version hash and git commit. |
| Run store | `runs/evals.sqlite`: every run, with each case's answer and scores. |
| Case score | One number per case, `case_score`, to compare runs case by case. |
| Primary metric | The component's first metric, which says better or worse. |
| Compare verdict | Better, worse or no change per metric; both runs' stored answers are scored on the current gold. |
| Trace | A call's steps, as `<run id>:<case id>`; see `resourcly request`. |
| `evals check` | Checks every gold file and split. |

Each component has one suite in `suites.py`, the code defining its test: load, call, score and
metrics, primary first.

## Modules

| File | Job |
| --- | --- |
| `cli.py` | The `evals` command. |
| `harness.py` | Runs a version on its cases and stores the results. |
| `suites.py` | One suite per component. |
| `cases.py` | Loads gold cases; checks the gold and splits. |
| `metrics.py` | Pure scoring functions. |
| `gold_rules.py` | Drawing gold checks the models do not make. |
| `compare.py` | Scores two runs on the current gold. |
| `models.py` | `Run` and `CaseResult`. |
| `store.py` | The run store in SQLite. |

## Components

| Component | Task | Primary metric | Other metrics |
| --- | --- | --- | --- |
| `reader` | drawing to JSON | `f1` | `precision`, `recall`, `partial_recall` |
| `router` | request to its case | `accuracy` | `drawing_recall`, `other_kept_out` |
| `failure` | photo to report figure | `section@1` | `mode@3`, `kept_out` |

## Add a version

Copy a file in `versions/<component>/` and edit it. `impl` must be in `READERS`, `ROUTERS` or
`FINDERS` in `bootstrap.py`, and other keys must be settings it lists.

## Add a component

Write its port and an implementation, registered in `bootstrap.py`, then add its suite, case
loader and metrics. Nothing else changes.
