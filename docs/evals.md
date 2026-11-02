# Running the evals

How to run the eval harness, and the numbers it gives today. What the harness is, its concepts
and its modules: [src/resourcly/eval_harness/README.md](../src/resourcly/eval_harness/README.md).

## Commands

```sh
uv run evals check                                   # every gold file and split
uv run evals run router --version stub-v0            # the dev split by default
uv run evals run reader --version textlayer-v0 --split all
uv run evals run failure --version shuffled-v0 --limit 10   # a partial run of 10 cases
uv run evals show RUN_ID --failures                  # the cases that scored below 1
uv run evals show RUN_ID --case CASE_ID              # one case against its gold
uv run resourcly request RUN_ID:CASE_ID              # what one call did
uv run evals compare failure shuffled-v0 my-finder-v1 --fail-if-worse
```

`--split` takes dev, test or all, and train for the router. `--limit N` runs a partial sample,
spread over the strata in proportion with seed 0, so it is the same each time.

`compare` takes run ids or version names; a version stands for its latest run on every case of a
split. It scores both runs' stored answers on the current gold, so a gold fix needs no rerun. It
refuses runs on other splits or cases unless `--force`, and `--fail-if-worse` also fails when
the primary metric was not measured. Runs are stored in `runs/evals.sqlite`. Tune on dev, and
run test only at milestones.

Three components are measured today. Answering questions from the reports, and a score for the
whole agent, are planned as further components.

## Current numbers

The model-free version of each component sets its floor.

| Version | Split | Primary | Other |
| --- | --- | --- | --- |
| reader `textlayer-v0` | all, 11 drawings | f1 0.344 | precision 0.902, recall 0.213, partial_recall 0.129 |
| router `stub-v0` | dev, 123 requests | accuracy 0.607 | drawing_recall 0.120, other_kept_out 0.500 |
| failure `shuffled-v0` | dev, 86 photos | section@1 0.038 | mode@3 0.769, kept_out 0.000 |

## What each metric means

| Metric | Meaning |
| --- | --- |
| `f1`, `precision`, `recall` | Reader values that match the full gold on page, unit, kind and number. |
| `partial_recall` | Recall on partial gold, which lists only some values per drawing. |
| `accuracy` | Router requests with a case (drawing, photo, text) sent to the right one. |
| `drawing_recall` | Drawings the router sends to the reader. |
| `other_kept_out` | Files that fit no case, routed to `other`. |
| `section@1` | Photos whose top figure is in the right report section. |
| `mode@3` | Photos with the right failure mode in the top three figures. |
| `kept_out` | Drawings and unrelated images that get no figure. |

A failed call is scored as an empty answer, so a crash lowers the score.
