# Routing each request

**Answer:** use a layered router, cheapest layer first.
Structure rules on the file come first. A DINOv2-small probe follows, deciding when it is at least 90% sure. Qwen3-VL 8B takes the rest.
On 244 labelled requests it made 0 mistakes on the 224 that have a case.
It sent 2.5% to 3.9% of drawings and photos to the model, and cost 34 ms per file at the median.
The full results, with pictures, are in [`review.html`](review.html).

## The question

The brief says the agent decides by itself which case a request is, and the user never says.
A technical drawing gets every value back as JSON.
A photo of a part gets an explanation of what is wrong, from the NTSB reports, and a text question gets an answer from the reports.
Some files fit none of these, such as a whole report or a logo, and must not be pushed into a case.
Everything runs locally (here, a MacBook Pro M1 Pro with no network), must be cheap at a million documents, and must be measurable.

The labelled set has 244 requests: 116 drawing files, 88 photo files, 20 questions, 10 messages sent with a file, and 10 files that fit no case.
They come from the NIST drawings, the NTSB reports and 20 Wikimedia Commons files, and many drawing files are copies made by code: renders, heavy JPEGs, rotations, crops, fake phone photos and scans.
Every split keeps one drawing, report or Commons file on one side, so near copies never leak.
[`dataset.html`](dataset.html) shows every item.

## Options tried

Accuracy is on the 204 drawing and photo files.

| Option | What it is | Key result | Verdict |
| --- | --- | --- | --- |
| A. Rules | PDF structure, camera EXIF, pixel statistics | 51.9% on held-out files with EXIF; exact on CAD PDFs | Keep only the PDF structure rules |
| B. Linear probe | Logistic regression on a frozen image embedding | 99.5% to 100%, about 30 ms per image | Layer 2, DINOv2-small |
| C. Zero-shot | CLIP or SigLIP 2 against text descriptions | SigLIP 2 100%, CLIP 99.0% | Fallback before labels exist |
| G. Docling classifier | Pretrained 26-class figure classifier | 75.0% | Not used |
| D. Vision-language model | Qwen3-VL 2B, 4B, 8B, one question | 99.5% to 100%, 1.1 to 3.5 s per image | Layer 3, the 8B |
| F. Decision model | LiquidAI d1, a probability per option | 92.6% to 99.5%, 0.13 to 0.75 s | d1-2B after a licence check |
| Hosted decision APIs | Typesafe's Jev, OpenAI's Decisions API | Not measured | Ruled out: the file leaves the system |
| E. Layered router | A, then B, then D when B is unsure | 0 mistakes | Recommended |

## Recommendation

| Layer | Decides | Share of drawings and photos | Time |
| --- | --- | --- | --- |
| 1. Structure rules | No attachment is text. A PDF with CAD sheets is a drawing. A PDF with more prose pages is a document that fits no case. | 5.9% | 14 to 37 ms per CAD PDF |
| 2. DINOv2-small probe | Drawing or photo, when at least 90% sure | 91.2% | 32 ms |
| 3. Qwen3-VL 8B | Drawing, photo or something else | 2.9% (2.5% to 3.9%) | 1.2 to 3.5 s |

The result is 0 mistakes on 224 labelled requests, a 34 ms median and a 104 to 141 ms mean per drawing or photo.
Six of the 10 files that fit no case stay out of the drawing and photo cases; two get a case, and two were not measured.
The times are rebuilt from measured steps, not timed end to end.

Why three layers:

- The probe alone also made no mistake, but it sent all 10 files that fit no case to the drawing case. The rules catch the report PDFs, and the model catches logos and a report page.
- The rules are exact where they decide, so a bulk upload of CAD drawings rarely reaches a model.
- The probe is about 100 times cheaper than the model. At a million images, the model sees 24,500 to 39,200 files, or 24 to 38 hours.

The 0.9 threshold is a default: no threshold from 0.5 to 0.995 made a mistake here.

## What each option got wrong

- **Pixel and EXIF rules** sent 14 of the 15 phone photos of drawings to the photo case, because a phone photo of a drawing looks like a part photo.
- **Probes** learn their drawing family. Trained without NIST drawings, DINOv2 got 8 of 109 NIST files wrong, and the Docling features got none wrong. A two-class probe also calls report PDFs drawings.
- **Docling's classifier** called most coloured NIST sheets "geographical_map".
- **Qwen3-VL 4B and 8B** called a bare sheet metal flat pattern "something else". The probe gets it right first.
- **d1-omni-600M** got 7.4% wrong and followed a misleading user message on 4 of 10 pairs.

## Risks and open questions

Risks:

- The set is small and partly made by code, so it shows which designs fail more than it ranks the ones that work.
- Which image model the probe should use is not settled. Keep it easy to swap, and choose it again on the customer's drawings.
- The probe and threshold were set with the files that fit no case in view, so those counts are optimistic.
- PyMuPDF is AGPL-3.0, and the d1 models cap commercial use.

| Open question | Default chosen |
| --- | --- |
| A file that fits no case | Its own outcome; the reply says it fits neither case |
| A drawing sent with a question | The drawing case; the user's text never changes the case |
| Route a PDF page by page? | No; the first ten pages at most, the probe reads page 1 |
| Four files added after the model runs | Not measured; `run_models.py --update` fills them in |

## Re-run and details

[`experiments/routing/README.md`](../../experiments/routing/README.md) re-runs the notebook from the stored results in about a minute, with no model.
The details are in [`review.html`](review.html), [`routing.ipynb`](../../experiments/routing/routing.ipynb) and [`results/`](../../experiments/routing/results/).

Model cards used: [DINOv2 small](https://huggingface.co/facebook/dinov2-small), [Qwen3-VL 8B MLX 4-bit](https://huggingface.co/mlx-community/Qwen3-VL-8B-Instruct-4bit), [SigLIP 2 base](https://huggingface.co/google/siglip2-base-patch16-224), [Docling figure classifier](https://huggingface.co/docling-project/DocumentFigureClassifier-v2.5), [LiquidAI d1-2B](https://huggingface.co/LiquidAI/d1-2B).
