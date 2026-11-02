# Answering a photo of a part

When the router calls a file a photo, the agent says what is wrong with the part and what to do,
using only the three NTSB reports in `data/reports/`. The design comes from
[research/failure](../research/failure/README.md). Everything runs on the machine.

## How a photo is answered

1. **Find.** The failure finder `dinov2-base-v1` turns the photo into a DINOv2-base vector (the
   class token joined to the mean of the patch tokens, from the centre 224 px square). It ranks
   the 46 report figures by cosine similarity to it and returns the closest 5
   (`adapters/nearest_figures.py`).
2. **Gate.** When even the closest figure is below 0.28, the answer is that the reports do not
   show this failure, and no language model is asked.
3. **Answer.** The answer version `photo-v1` makes one call to Qwen3-VL 8B. The model sees the
   photo, the 2 closest figures as images, and the text of the 3 closest: each one's labels,
   caption and citing paragraphs, and its report's closing paragraphs. The user's text is the
   question. Without text, the question is what is wrong and what to do
   (`adapters/vlm_answer.py`).
4. **Check.** Code keeps a finding only when its source, such as `18-061 fig05` or `18-061 p3`,
   is one the model was shown. An action is "stated" only when it cites report text it was shown;
   any other action is "inferred" (`answers.py`).

The photo's item goes from `queued` to `answering` to `answered`. Its `answer` holds the answer
text, the findings and actions with their citations, the closest figures with their scores, and
`not_in_reports`, which is true when the gate kept the photo out. `reply` is the same answer as
text. `GET /api/reports/<report>/figures/<n>.png` serves a cited figure ([usage.md](usage.md)).

The trace has two steps for a photo: `failure.find`, the figures found, and `answer.photo`,
what the model was shown, what it answered and the sources that were dropped. The user's text is
kept as its length and hash only.

## Models

The answer uses the same Qwen3-VL 8B adapter as the reader and the router, so the model loads
once. DINOv2-base is loaded beside the router's DINOv2-small, about 350 MB and 90 MB: the
research found small worse at finding figures (below).

```sh
uv sync --extra router --extra vlm
uv run hf download facebook/dinov2-base
uv run hf download mlx-community/Qwen3-VL-8B-Instruct-4bit
```

`RESOURCLY_FAILURE_VERSION=shuffled-v0` and `RESOURCLY_ANSWER_VERSION=captions-v0` answer with no
model: the figures in a fixed random order, and their captions as the answer.

## The figure index

`versions/failure/indexes/<version>.json` holds every figure with its report, page, box, section,
failure mode, caption and citing paragraphs, each report's closing paragraphs, and the figure
vectors. It records the encoder, the vector recipe and the input size, and a finder with another
encoder refuses it. The figure images are not kept; each is rendered again from its PDF.
`scripts/build_figure_index.py` cuts the PDFs and writes it; the labels come from
`data/reports/sections.toml`.

```sh
uv run --extra router python scripts/build_figure_index.py \
    --encoder-model facebook/dinov2-base --out versions/failure/indexes/dinov2-base-v2.json
```

## Results

The failure gold scores the finder only ([evals.md](evals.md)). Its photos are changed copies of
the figures the index holds, so both DINOv2 versions find every one. With each photo's own figure
hidden, as for a real photo, base finds the right report first for 95.7% of the 138 photos and
small for 89.9%, with the same vector recipe (the research's 90.6% for small used the router's
class token alone).

The gate keeps out all 5 unrelated images of the gold with base, and none of the 11 drawings,
which the router keeps away. On 12 real photos of other broken parts it keeps out only 2: a
fracture photo can be closer to a report figure than 0.28. Then the model must say that the
figures show a different part. It did for a Roman lock bolt, and did not for a generic ductile
fracture surface, which it answered as the spar fatigue of 18-061.

By hand on 6 report photos, 4 are right: the spar fatigue of 18-061 fig05, the overstress of
24-013 fig04, and "no defect" on two reference parts the research's model had rejected (16-006
fig05, 18-061 fig21). On 18-061 fig24 it said the spar cross-section was not a spar. On 16-006
fig04 it took the mixture control's bent rod, from the third figure's text, for the throttle
lock. The answer step takes 19 to 34 s, the model load included; the research's took about 2
minutes.

## Limits

- The answers are checked by hand on 9 photos; there is no labelled answer gold yet.
- The report photos are figures changed by code. Real photos of these parts are untested.
- An unrelated photo of a fracture can pass the gate, and the model may then answer it.
