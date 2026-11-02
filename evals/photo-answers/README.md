# Photo answers, checked by hand

There is no answer gold yet, so photo answers are checked by a person on stored runs.

- `cases.jsonl`: 18 photos under `../gold/`. 6 are report photos (changed copies of report
  figures, with the figure they show) and 12 are real photos of other broken parts, which the
  reports do not cover.
- `spot-check.jsonl`: 6 of them, 3 of each kind.
- `runs/<version>-<set>.jsonl`: what `scripts/check_photo_answers.py` stored for each case: the
  answer, the model's own text and the seconds it took.
- `verdicts/<version>-<set>.jsonl`: a person's verdict on each answer, right or wrong, and why.

| Run | Right | Wrong |
| --- | --- | --- |
| `photo-v2` spot check, 6 photos | 4 | 2: an intact lock mechanism rejected; a ductile fracture answered as spar fatigue |

Pending: the full 18-photo run of `photo-v1` and `photo-v2`, to compare the two.

```sh
uv run --extra router --extra vlm python scripts/check_photo_answers.py \
    --cases evals/photo-answers/spot-check.jsonl --out evals/photo-answers/runs/photo-v2-spot.jsonl
```
