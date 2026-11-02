# Eval harness

The eval harness tests each part of the agent on its own: run a version of a part on chosen
gold cases, and see whether it beats another version. Commands and current numbers:
[docs/evals.md](../../../docs/evals.md).

```text
gold cases + split -> version file -> call through open_services() -> score per case
                                                                          |
                          compare <- stored run (answers and scores) <----+
```

## Concepts

| Concept | What it is |
| --- | --- |
| Component | The part of the agent under test: `reader`, `router`, `failure` or `answer`. |
| Setting | A second suite of one component, such as `failure-copy`; it runs that component's versions. |
| Gold case | An input and its known answer, in `evals/gold/`; partial gold gives recall only. |
| Split | Dev and test cases, in `evals/splits.toml`; related cases stay together. |
| Version file | `versions/<component>/<name>.toml`: an implementation and its settings. |
| Implementation | Code behind the component's port, registered as `impl` in `bootstrap.py`. |
| Run | One version on one split, with its version hash and git commit. |
| Run store | `runs/evals.sqlite`: every run, with each case's answer and scores. |
| Case score | `case_score`, one number per case, to compare runs case by case. |
| Primary metric | The component's first metric, which says better or worse. |
| Compare verdict | Better, worse or no change per metric, scoring both runs on the current gold and the same cases. |
| Trace | A call's steps; `resourcly request <run id>:<case id>`. |

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
| `models.py` | `Case`, `Run` and `CaseResult`. |
| `store.py` | The run store in SQLite. |

## Components

| Component | Task | Primary metric | Other metrics |
| --- | --- | --- | --- |
| `reader` | drawing to JSON | `f1` | `precision`, `recall`, `partial_recall` |
| `router` | request to its case | `accuracy` | `drawing_recall`, `other_kept_out` |
| `failure` | photo to report figure, its own figure hidden | `section@1` | `mode@3`, `kept_out` |
| `failure-copy` | the same with its own figure in the search | `section@1` | `mode@3`, `kept_out` |
| `answer` | photo to a cited answer, held out | `correct` | `report_cited`, `mode_named`, `citations_valid`, `kept_out` |

Held out is the realistic setting: a real photo is never a copy of an indexed figure, so the
finder must reach another figure of the same section. The answer runs the failure version the
settings name. A whole-agent score is a planned component.

## Add a version

Copy a file in `versions/<component>/` and edit it. `impl` must be in `READERS`, `ROUTERS`,
`FINDERS` or `ANSWERERS` in `bootstrap.py`, and other keys must be settings it lists.

## Add a component

Write its port and an implementation, registered in `bootstrap.py` with a default version.
Then add its suite, case loader and metrics; the CLI, harness and `compare` find it in `SUITES`.
