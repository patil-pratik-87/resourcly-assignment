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
uv run evals compare failure dinov2-small-v1 dinov2-base-v1 --fail-if-worse
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

The model-free version of each component sets its floor. The two vision readers need
`--extra vlm`; the drawing notebooks compare them (`experiments/drawing/README.md`).

| Version | Split | Primary | Other |
| --- | --- | --- | --- |
| reader `textlayer-v0` | all, 11 drawings | f1 0.344 | precision 0.902, recall 0.213, partial_recall 0.129 |
| reader `whole-page-v1` | all, 11 drawings | f1 0.650 | precision 0.629, recall 0.672, partial_recall 0.543 |
| reader `vector-crop-v1` | all, 11 drawings | f1 0.725 | precision 0.625, recall 0.862, partial_recall 0.743 |
| router `stub-v0` | dev, 123 requests | accuracy 0.602 | drawing_recall 0.120, other_kept_out 0.500 |
| failure `shuffled-v0` | dev, 86 cases | section@1 0.038 | mode@3 0.769, kept_out 0.000 |
| failure `dinov2-base-v1` | dev, 86 cases | section@1 1.000 | mode@3 1.000, kept_out 0.375 |
| failure `dinov2-base-v1` | test, 68 cases | section@1 1.000 | mode@3 1.000, kept_out 0.250 |
| failure `dinov2-small-v1` | dev, 86 cases | section@1 1.000 | mode@3 1.000, kept_out 0.000 |
| failure `dinov2-small-v1` | test, 68 cases | section@1 1.000 | mode@3 1.000, kept_out 0.125 |

A failure split's cases are photos of report figures and negatives: 78 and 8 in dev, 60 and 8 in
test. The photos are changed copies of figures the DINOv2 finders index, so both find every one;
with each photo's own figure hidden, base finds the right report first for 95.7% and small for
89.9% ([photo-answers.md](photo-answers.md)). `kept_out` counts drawings, which the router keeps
from the finder: base keeps out all 5 unrelated images and none of the 11 drawings, small 1 and
none. The photo answer itself has no gold yet.

## What each metric means

| Metric | Meaning |
| --- | --- |
| `f1`, `precision`, `recall` | Reader values that match the full gold on page, unit, kind and number. |
| `partial_recall` | Recall on partial gold, which lists only some values per drawing. |
| `accuracy` | Router requests sent to the right route, files that fit no case included. |
| `drawing_recall` | Drawings the router sends to the reader. |
| `other_kept_out` | Files that fit no case, routed to `other`. |
| `section@1` | Photos whose top figure is in the right report section. |
| `mode@3` | Photos with the right failure mode in the top three figures. |
| `kept_out` | Drawings and unrelated images that get no figure. |

A failed call is scored as an empty answer, so a crash lowers the score.
