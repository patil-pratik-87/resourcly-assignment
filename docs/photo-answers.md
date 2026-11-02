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
   show this failure, and no language model is asked. The gate keeps out pictures far from any
   part. It does not hold on real photos of other broken parts: 10 of the 12 checked score above
   it, so the next step must keep them out.
3. **Answer.** The answer version `photo-v2` makes one call to Qwen3-VL 8B. The model sees the
   photo, the 2 closest figures as images, and the text of the 3 closest: each one's labels,
   caption and citing paragraphs, and its report's closing paragraphs. The user's text is the
   question. Without text, the question is what is wrong and what to do
   (`adapters/vlm_answer.py`). The same answer says what the photo is, and whether it shows the
   same failure as the reference images: the same kind of damage on the same kind of part, or the
   same intact part for a figure of a part with no defect.
4. **Check.** A photo the model calls unrelated or a technical drawing is kept out, the
   research's second check after the gate. Code keeps a finding only when its source, such as
   `18-061 fig05` or `18-061 p3`, is one the model was shown, and a match with no kept finding is
   given as no match. An action is "stated" only when it cites a report paragraph it was shown and
   quotes words of that paragraph exactly; a figure caption is not enough. Any other action is
   "inferred" (`answers.py`).

The photo's item goes from `queued` to `answering` to `answered`. Its `answer` holds the answer
text, the findings and actions with their citations, the closest figures with their scores,
`matched`, and `not_in_reports` with `kept_out`, which says whether the gate or the unrelated
check kept the photo out. `reply` is the same answer as text. `GET /api/reports/<report>/figures/<n>.png` serves a cited figure
([chat-ui.md](chat-ui.md#the-api)).

```json
{
  "not_in_reports": false,
  "kept_out": null,
  "matched": true,
  "answer": "Fatigue cracks grew from the attachment holes of the lower spar cap.",
  "findings": [
    {"statement": "Fatigue origins were at the lower surface near hole LC-1.",
     "citation": {"source": "18-061 p2", "report": "18-061", "page": 2, "figure": null}}
  ],
  "actions": [
    {"action": "Inspect the spar cap at the attachment holes.", "basis": "inferred",
     "citation": null, "quote": null}
  ],
  "figures": [
    {"figure": "18-061/fig05", "report": "18-061", "section": "spar_fatigue_N106ER",
     "failure_mode": "fatigue", "score": 0.78}
  ]
}
```

`kept_out` is `gate` when no report figure is close enough and `unrelated` when the model sees no
part; the answer then says so and has no findings, actions or figures. A `stated` action's `quote`
holds the words of the cited page that say to do it.

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

The failure gold scores the finder and the answer ([evals.md](evals.md)). Its photos are changed
copies of the figures the index holds, so in the copy setting (`failure-copy`) both DINOv2
versions find every one. With each photo's own figure hidden, as for a real photo and the
`failure` eval, base finds the right report first for 95.7% of the 138 photos and
small for 89.9%, with the same vector recipe (the research's 90.6% for small used the router's
class token alone).

The gate keeps out all 5 unrelated images of the gold with base, and none of the 11 drawings,
which the router keeps away. It does not hold on real photos of other broken parts: 10 of the 12
in `evals/photo-answers/` score above 0.28, so the answer's own check must keep them out.

A stored spot check of `photo-v2` on 6 photos (`evals/photo-answers/`) has 4 right: the spar
fatigue of 18-061 fig05, the overstress of 24-013 fig04, a broken VCR part kept out by the gate
and a Roman lock bolt answered as no match. 2 are wrong: it rejects the intact lock mechanism of
16-006 fig05, which `photo-v1` answered as no defect, and it answers a ductile fracture that is
not in the reports as the spar fatigue of 18-061. An answer takes 20 to 38 s. The full 18-photo
run of `photo-v1` against `photo-v2` is pending.

## Limits

- There is no labelled answer text. Answers are scored by the `answer` eval on 8 sampled gold
  cases and checked by hand on stored runs.
- The report photos are figures changed by code. Real photos of these parts are untested.
- A real photo of a fracture that is not in the reports can pass the gate, and the model may then
  answer it as a report's failure.
