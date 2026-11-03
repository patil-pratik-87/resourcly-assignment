# Running the evals

How to run the eval harness, and the numbers it gives today. What the harness is, its concepts
and its modules: [src/resourcly/eval_harness/README.md](../src/resourcly/eval_harness/README.md).

## Commands

```sh
uv run evals check                                   # every gold file and split
uv run evals run router --version stub-v0            # the dev split by default
uv run evals run reader --version textlayer-v0 --split all
uv run evals run failure --version shuffled-v0 --limit 10   # a partial run of 10 cases
uv run evals run failure-copy --version dinov2-base-v1      # the photo's own figure kept
uv run --extra vlm evals run answer --version photo-v2 --limit 8
uv run evals run answer-copy --case-id pos_18-061_fig05_v0  # as the app answers an upload
RESOURCLY_ANSWER_VERSION=captions-v0 uv run evals run qa --version rules-v0 --split all  # no 8B
uv run evals run reader-pictures --version vector-crop-v2 --limit 4   # pictures of drawings
uv run evals run agent --version select-v1 --limit 7         # whole conversations, one per case
uv run evals show RUN_ID --failures                  # the cases that scored below 1
uv run evals show RUN_ID --case CASE_ID              # one case against its gold
uv run resourcly request RUN_ID:CASE_ID              # what one call did
uv run evals compare failure dinov2-small-v1 dinov2-base-v1 --fail-if-worse
```

`--split` takes dev, test or all, and train for the router. `--limit N` runs a partial sample,
spread over the strata in proportion with seed 0, so it is the same each time. Without
`--version`, a run uses the version the app runs. On a terminal, a run draws a progress bar
under its case lines.

`compare` takes run ids or version names; a version stands for its latest run on every case of a
split. It scores both runs' stored answers on the current gold, so a gold fix needs no rerun. It
refuses runs on other splits or cases unless `--force`, and `--fail-if-worse` also fails when
the primary metric was not measured. Runs are stored in `runs/evals.sqlite`. Tune on dev, and
run test only at milestones.

Five components are measured, and `agent` scores the whole agent on whole conversations.

The `qa` suite asks 80 questions: 30 about the drawings CTC-01, CTC-03 and FTC-06 (16 of them
name a place on the part), 20 about failure photos, 20 about the reports with the pages that
answer them, and 10 that nothing answers. A case scores 1 for a right answer, 0.5 when the right
value is among candidates to tap, 0 for no answer and -1 for a wrong value, page or figure shown.
A drawing question is answered from the reader's JSON in `outputs/`, or from the gold values with
a version whose `evidence` is `gold`. Its photo questions run the photo answer the settings name.

`reader-pictures` reads the router gold's pictures of NIST drawing pages, images and scans, as the
chat reads an image upload, and scores each against its page's gold. `agent` sends 29
conversations of 34 messages to the agent over the seven cases (a question alone, with a photo,
with a drawing, with a picture of a drawing, with a file that fits no case, many files with one
text, and a follow-up), and a conversation is fully right when every file gets its route and every
answer is right and on the right card. Its requests are kept in `runs/agent-uploads/`, apart from
the chat's, with a read cache, so a drawing it sent before is not read again.

The failure and answer suites run held out: each photo is a perturbed copy of a report figure,
so its own figure is hidden from the search and the best hit must be another figure of its
section. `failure-copy` keeps the figure in, which only checks that the perturbations do not
break matching, and `answer-copy` keeps it in as the app does for an uploaded photo. The answer runs the failure version the settings name
(`RESOURCLY_FAILURE_VERSION`, `dinov2-base-v1` by default), and `photo-v1` took 18 to 35 s per
photo with Qwen3-VL 8B, so run it with `--limit`.

## Current numbers

The model-free version of each component sets its floor. The two vision readers need
`--extra vlm`; the drawing notebooks compare them (`experiments/drawing/README.md`).

| Version | Split | Primary | Other |
| --- | --- | --- | --- |
| reader `textlayer-v0` | all, 11 drawings | f1 0.344 | precision 0.902, recall 0.213, partial_recall 0.129 |
| reader `whole-page-v1` | all, 11 drawings | f1 0.650 | precision 0.629, recall 0.672, partial_recall 0.543 |
| reader `vector-crop-v1` | all, 11 drawings | f1 0.725 | precision 0.625, recall 0.862, partial_recall 0.743 |
| router `stub-v0` | dev, 123 requests | accuracy 0.602 | drawing_recall 0.120, other_kept_out 0.500 |
| failure `dinov2-base-v1` | all, 154 cases | section@1 0.645 | mode@3 0.942, kept_out 0.312 |
| failure `dinov2-small-v1` | all, 154 cases | section@1 0.551 | mode@3 0.913, kept_out 0.062 |
| failure `shuffled-v0` | all, 154 cases | section@1 0.022 | mode@3 0.739, kept_out 0.000 |
| failure-copy `dinov2-base-v1` | all, 154 cases | section@1 1.000 | mode@3 1.000, kept_out 0.312 |
| failure-copy `dinov2-small-v1` | all, 154 cases | section@1 1.000 | mode@3 1.000, kept_out 0.062 |
| answer `captions-v0` | dev, 86 cases | correct 0.535 | report_cited 0.987, mode_named 0.564, citations_valid 1.000, kept_out 0.375 |
| answer `captions-v0` | dev, `--limit 8` | correct 0.500 | report_cited 1.000, mode_named 0.500, citations_valid 1.000, kept_out 0.500 |
| answer `photo-v1` | dev, `--limit 8` | correct 0.625 | report_cited 0.667, mode_named 0.667, citations_valid 1.000, kept_out 0.500 |
| answer `photo-v2` | dev, 86 cases | correct 0.500 | report_cited 0.526, mode_named 0.782, citations_valid 1.000, kept_out 0.500, prompt_free 0.442 |
| answer `photo-v3` | dev, 86 cases | correct 0.523 | report_cited 0.551, mode_named 0.769, citations_valid 1.000, kept_out 0.500, prompt_free 1.000 |
| qa `rules-v0`, photos by `captions-v0` | all, 80 cases | answer_score 0.356 | wrong_shown 0.200, drawing 0.214, place 0.469, photo 0.400, text 0.500, none 0.000 |
| qa `select-v1`, photos by `photo-v3` | all, 80 cases | answer_score 0.644 | wrong_shown 0.050, drawing 0.643, place 0.469, photo 0.300, text 0.950, none 1.000 |
| reader-pictures `vector-crop-v1` | dev, 41 pictures | f1 0.000 | it reads nothing from a page with no vector paths |
| reader-pictures `vector-crop-v2` | dev, the 17 with full gold | f1 0.405 | precision 0.351, recall 0.479 |
| agent `select-v1`, the default versions | dev, 29 conversations | fully_right 0.828 | routes 1.000, cards 1.000, answer_score 0.833, json_f1 0.775 |

A failure split's cases are photos of report figures and negatives: 78 and 8 in dev, 60 and 8 in
test. Held out, `dinov2-base-v1` repeats the research exactly (`research/failure/README.md`):
report@1 95.7%, section@1 64.5%, mode@1 79.0%, mode@3 94.2%. `dinov2-small-v1` is lower than the
research's DINOv2-small (section@1 55.1% against 58.0%, report@1 89.9% against 90.6%) but mode@3
is higher (91.3% against 90.6%). The research measured the router's class-token vector, and this
version uses the class token joined to the patch mean. In the copy setting both find every photo.
No finder keeps a drawing out: the 0.28 gate is below what drawings reach (0.42), so the router
must keep them out. `dinov2-base-v1` keeps all 5 unrelated images out, and `dinov2-small-v1`
keeps 1.

`select-v1` shows no wrong drawing value: every `-1` is a photo case. Place questions stay at 0.5
each, as candidates, and photo questions score lower with the user's question than with the
default one (0.300 against 0.500 on the same 20 photos); more in
[NOTES.md](../NOTES.md#questions). The agent's 5 misses are a units question twice, where the
model names the wrong kind, and three values the reader misread or missed.

`photo-v2` told users about "reference image 1" or copied the prompt's rule for an inferred
action in 48 of 86 answers. `photo-v3`, now the default, names figures by their source and shows
that rule as a JSON example; every answer is prompt free, and correct moves from 0.500 to 0.523.
The `photo-v1` runs score the same under the current rules, since none of its actions is stated.

On its 8 cases, `photo-v1` answers 4 of 6 photos correctly and the captions floor 3. Both photos
it gets wrong had a top figure from another report, and the model followed it. It keeps the logo
out, at the gate. It does not keep the drawing out: the drawing passes the gate and the model
calls it spar fatigue. Every citation is valid in both runs. Eight cases are too few to rank the
two versions.

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
| `kept_out` | Drawings and unrelated images that get no figure; for `answer`, an answer that says the reports say nothing about it, at the gate or because the model saw no part. |
| `correct` | Answers that are right: a photo's answer is a match, cites its report, names its failure mode and cites only valid sources; a negative's is kept out. |
| `report_cited` | Photo answers with a citation in the photo's report. |
| `mode_named` | Photo answers whose text or findings have a word starting with one of the failure keywords. |
| `citations_valid` | Citations that name a figure the finder returned, or a page of their reports, and whose source agrees; a stated action's must cite a page and quote at least three words. |
| `prompt_free` | Answers whose text, findings and actions use none of the prompt's own words, such as "reference image" or the `basis` and `quote` fields. |
| `answer_score` | The mean qa case score, from -1 to 1; per kind of question it is `drawing`, `place`, `photo`, `text` and `none`. |
| `wrong_shown` | Questions whose answer showed a wrong value, page or figure; lower is better. |
| `fully_right` | Agent conversations whose last message got every route, card and answer right. |
| `routes`, `cards`, `json_f1` | For `agent`: items routed right, answers on the right cards, and the drawings' JSON against their gold. |

A failed call is scored as an empty answer, so a crash lowers the score.
