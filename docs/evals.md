# The eval harness

The `resourcly.evals` package scores each version of the drawing reader on its gold cases and says
whether a new version got better or worse. It reaches the app only through `open_services()` in
`bootstrap.py`, so it measures the code the app runs. `tests/test_architecture.py` enforces that.

```sh
uv run evals check                                  # gold files and splits
uv run evals run reader --version textlayer-v0      # dev split by default
uv run evals show RUN_ID --case nist_ctc_01_asme1_rd
uv run evals compare reader textlayer-v0 my-reader-v1 --fail-if-worse
uv run evals show --request REQUEST_ID              # what one call did
```

## How a run works

1. Open the services with `versions/<component>/<name>.toml`.
2. Load the gold cases of the split (`evals/splits.toml`), or only those `--case-id` names.
3. Call the reader on each case with request id `<run id>:<case id>`, which leaves a trace.
4. Store each case's raw prediction, error, time and scores in `runs/evals.sqlite`.
5. Store the run's summary, version hash, git commit and a hash of the cases and their gold.

A failed call is scored as an empty reading, so a crash lowers recall. Stored predictions let
`evals run --rescore RUN_ID` score an old run against corrected gold without calling the reader.

## The split

| Split | Drawings |
| --- | --- |
| dev | CTC-01, CTC-02, CTC-04, FTC-07, FTC-09 |
| test | CTC-03, FTC-06, CTC-05, FTC-08, FTC-10, FTC-11 |

Tune on dev; run test only at milestones.

## Reader metrics

| Metric | What it measures |
| --- | --- |
| `strict_f1` (primary) | Match on page, unit, kind and value; raw text when there is no number. Full gold only. |
| `loose_f1` | The same without kind. |
| `partial_recall` | Strict recall on partial gold, which lists about ten values per drawing, so it gives no precision. |
| `kind_accuracy` | Share of loose pairs with the right kind. |
| `feature_accuracy` | Share of strict pairs tied to the right type of feature. |

Both sides are normalised first: numbers to rounded floats, units to `mm`, `in` or `deg`, raw text
casefolded with one diameter sign. Matching is one to one. A record with no integer page or a
non-numeric value is invalid and counts as a wrong prediction. On a gold file with
`page_coverage`, predictions on other pages are not scored.

## Comparing versions

`evals compare` takes run ids or version names. It gives a verdict per metric only when both runs
saw the same cases and gold; otherwise rescore the older run first. It then lists each case by its
change in `case_score`. With five dev drawings, read a small change as noise.

## Adding a version

```toml
description = "One line on what this version changes"
impl = "textlayer"
# any other keys are settings of the implementation
```

`impl` must be in `READERS` in `bootstrap.py`, and every other key must be a setting that entry
lists. A new reader is an adapter of `ReaderPort` registered in `READERS`; the harness needs no change.
