# Saying what is wrong with a failed part

**Answer:** find the closest report figures with DINOv2-base alone, then let Qwen3-VL 8B write the
answer from the top 3 figures and their report text, citing each fact.
Retrieval is the solved half. With the source figure hidden, as it would be for a real photo,
DINOv2 returns the right report first for 95.7% of 138 photos and the right failure mode in the
top 3 for 94.2%, the best of the signals compared on both, in under 0.1 s per photo.
The router's DINOv2-small is worse on every held-out score, so it is not shared yet.
The answer step is the open half: in the only end-to-end run, Qwen3-VL 8B took 106 to 134 s per
photo and rejected the right figure in all 3 cases.
The full results, with charts, are in [`review.html`](review.html).

## The question

A user sends a photo of a failed part. The agent says what is wrong and what to do, based only
on the three NTSB materials laboratory reports in `data/reports/` (Mooney throttle and mixture
controls, Piper wing spars, Cessna throttle arm; 46 figures), and can then chat about it.
Everything runs locally on a MacBook Pro M1 Pro.

## The pipeline

1. **Ingest:** cut each PDF into figures (image, caption, citing paragraphs) and paragraphs.
2. **Describe:** Qwen3-VL 8B lists what it sees and the image type.
3. **Retrieve:** rank every figure by DINOv2 similarity to the photo.
4. **Gate:** answer "not in the reports" when the photo is far from every figure.
5. **Answer:** Qwen3-VL 8B sees the photo, the top 2 figures and the text of the top 3. It
   returns findings with sources such as `18-061 fig05`, and actions marked as stated in the
   report or inferred.

A text question goes to BM25 over the paragraphs and the same model; earlier user turns join the
search, so follow-ups stay on topic.

## How it was measured

There are no real photos of these parts, so the test photos are made from the report figures.
Each of the 46 figures is copied 3 times with a random crop, rotation, colour change, blur,
downscale and heavy JPEG: 138 positives. The 23 negatives are page 1 of the 11 NIST drawings and
12 unrelated photos. Each figure has a hand label from the report text: its section and a coarse
failure mode (fatigue 54, no defect 48, overstress 15, jammed control 15, heat damage 6). The
failure gold in `evals/gold/failure/` holds the same 149 images, but its 5 unrelated images
replace the 12 photos used here, so the gate floor must be checked there again.

- **Copy:** the source figure stays in the index, which only checks that the changes do not
  break matching.
- **Held out:** the source figure is hidden, so the best hit is another figure of the same
  section. This is the realistic setting, and it decides.

Report@1, section@1 and mode@1 check the top figure's report, section and failure mode;
mode@3 checks the top 3. Every retrieval option ran on all 161 cases; the describe and answer
steps ran on 3.

## Results

Held out, native input:

| Signal | Report@1 | Section@1 | Mode@1 | Mode@3 | Verdict |
| --- | --- | --- | --- | --- | --- |
| DINOv2-base image | 95.7% | 64.5% | 79.0% | 94.2% | Chosen |
| DINOv2-small, router's vector | 90.6% | 58.0% | 75.4% | 90.6% | Not shared |
| SigLIP 2 image | 93.5% | 60.1% | 81.2% | 92.8% | Dropped |
| SigLIP 2 + DINOv2, fused by rank | 93.5% | 60.9% | 82.6% | 91.3% | Dropped |
| SigLIP 2 photo to caption | 73.2% | 34.1% | 52.9% | 76.8% | Dropped |
| All three, fused | 92.8% | 47.8% | 68.8% | 87.7% | Dropped |

- **DINOv2-base alone is enough.** It is best on report@1 and mode@3. SigLIP 2 and the fusion
  stay within 6 photos and add a second model; captions are far behind.
- **Input shape barely matters.** Squashing, cropping, padding or keeping the aspect ratio moves
  report@1 between 91.3% and 97.8%, at most 10 photos, with no consistent winner.
- **The gate costs something with DINOv2 alone.** SigLIP 2 separated every negative, only just
  (0.718 against 0.722). With DINOv2, a floor above every negative (0.421, set by a drawing)
  keeps only 94.9% of positives.

## Recommendation

| Choice | Default | Why |
| --- | --- | --- |
| Retrieval | DINOv2-base image vectors alone, no fusion | Best on report@1 and mode@3; one image model |
| SigLIP 2, captions, BM25 | Off for photos | Within 6 photos or worse; BM25 was never measured |
| Input | Native (224 px centre crop) | Differences are 10 photos or fewer |
| Gate | DINOv2 best match below 0.28 means "not in the reports" | Keeps all 138 positives, rejects all 12 unrelated photos |
| Answer context | Top 3 figures, top 2 as images, plus each report's last paragraphs | Mode@3 is 94.2%, mode@1 79.0% |
| Model | Qwen3-VL 8B, local | Same model as routing and drawing |

The gate relies on the router: drawings never reach this step, so the 0.421 floor and its 5.1%
loss are avoided. Unrelated photos reach at most 0.271 and the worst positive is 0.294, a small
margin to check on real photos. The describe step's "unrelated" label stays as a second check,
never scored on negatives.

**Sharing the router's model is not worth it yet.** The router's probe uses DINOv2-small and its
pooled class token. Rerun with that vector and the same crop, small gets 7 fewer reports right,
9 fewer sections and 5 fewer failure modes in the top 3, out of 138. Each gap is small, but all
point the same way, and its best unrelated photo (0.308) now scores above its worst positive
(0.285). Keep base for retrieval; to reach one model file, measure the router's probe on
DINOv2-base instead, which takes seconds and no language model.

## What went wrong

- **The answer step rejected correct evidence.** All 3 end-to-end cases were no-defect
  reference figures, and the model said the photo matched nothing. The describe step also
  invented details, such as frost on a micrograph, that pulled the answer away.
- **Too slow for chat.** The describe step wrote up to 2,197 tokens; a case took 2 minutes.
- **Failure modes that look alike get mixed.** Of 29 photos with the wrong mode at rank 1, 10
  mix fatigue with no-defect spar figures and 6 mix heat damage with the jammed control.

## Risks and open questions

- The positives are report figures changed by code, so the held-out numbers are an upper bound.
- The answer step was scored on 3 cases and the chat not at all. Both need labelled questions
  and answers, checked for the right report, failure mode and valid citations.
- 12 unrelated photos cannot set a gate threshold; it needs real photos of other parts.

Model cards: [DINOv2 base](https://huggingface.co/facebook/dinov2-base),
[DINOv2 small](https://huggingface.co/facebook/dinov2-small),
[Qwen3-VL 8B](https://ollama.com/library/qwen3-vl).
