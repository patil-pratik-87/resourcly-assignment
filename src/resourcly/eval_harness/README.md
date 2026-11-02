# Eval harness

The eval harness measures each part of the agent. You plug in a version of a part, run it on
chosen gold cases, and see whether it got better or worse than another version. Commands and
current numbers: [docs/evals.md](../../../docs/evals.md).

```text
gold cases + split  ->  version file  ->  call through open_services()  ->  score per case
                                                                                  |
                       compare  <-  stored run (answers, scores, summary)  <-------+
```

## Concepts

| Concept | What it is |
| --- | --- |
| Component | A part of the agent that is measured on its own: `reader`, `router` or `failure`. |
| Suite | How one component is measured: load its cases, call it, score a case, sum up a run. |
| Gold case | One input with its known answer, under `evals/gold/`. Full gold lists every answer. Partial gold lists some, so it gives recall only. |
| Split | Which cases are dev and which are test, in `evals/splits.toml`. Related cases stay on one side. |
| Version file | `versions/<component>/<name>.toml`: which implementation, with which settings. |
| Implementation | Code behind the component's port, registered by name as `impl` in `bootstrap.py`. |
| Run | One version on one split, with the version hash, the git commit and a hash of the cases. |
| Run store | `runs/evals.sqlite`: every run, with each case's raw answer, error, time and scores. |
| Case score | One number per case, `case_score`, so two runs can be compared case by case. |
| Primary metric | The one number that says better or worse; `--fail-if-worse` checks it. |
| Compare verdict | Better, worse or no change per metric. Given only when both runs saw the same cases and gold. |
| Rescore | Score a stored run again against corrected gold, without calling the component. |
| Trace | Every call leaves its steps under request id `<run id>:<case id>`. |
| `evals check` | Checks every gold file and split. |

## Modules

| File | Job |
| --- | --- |
| `cli.py` | The `evals` command: run, compare, show, list, check. |
| `harness.py` | Runs a version on its cases, stores each result, and rescores. |
| `suites.py` | One `Suite` per component, in `SUITES`. |
| `cases.py` | Loads each component's gold cases and checks the gold and splits. |
| `metrics.py` | Pure scoring functions: answers and gold in, numbers out. |
| `gold_rules.py` | Drawing gold checks the data models do not make. |
| `compare.py` | Metric verdicts and per-case changes between two runs. |
| `models.py` | What a run stores: `Run` and `CaseResult`. |
| `ports.py` | The run store's interface. |
| `store.py` | The run store in SQLite. |

## Components

| Component | What it does | Primary metric | Other metrics |
| --- | --- | --- | --- |
| `reader` | drawing to JSON values | `f1` | `precision`, `recall`, `partial_recall` |
| `router` | request to its case | `accuracy` | `drawing_recall`, `other_kept_out` |
| `failure` | photo to report figure | `section@1` | `mode@3`, `kept_out` |

## Add a version

Copy a file in `versions/<component>/` and change it. `impl` names an entry of `READERS`,
`ROUTERS` or `FINDERS` in `bootstrap.py`, and the other keys must be settings that entry lists.
The hash covers the settings, so `compare` warns about a version edited after its runs.

## Add a component

Write its port and an implementation, and register it in `bootstrap.py`. Then add a `Suite` to
`suites.py`, with its case loader in `cases.py` and its metrics in `metrics.py`. The harness, the
run store and `compare` need no change.
