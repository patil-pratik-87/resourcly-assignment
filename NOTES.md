## The problem

Build a private chat agent for industrial technical documents (the brief is in
`INSTRUCTIONS.md`). The user sends text, a picture, or both, and the agent decides on its own
which case applies:

- A photo of a part: say what is wrong and what to do, based on the three NTSB materials
  laboratory reports in `data/reports/`.
- A technical drawing: return JSON with every value on it, what each value belongs to and what
  it means.
- A question in text: answer it from the reports.

Around the agent: bulk upload of many drawings at once, no data leaving the machine, a design
that still works at over a million similar documents, a stored trace of every request for a
technical person, and code that measures each part and the whole system, so a new version can
be compared with the current one.

## The approach

- Everything runs locally on an Apple silicon laptop: open-weight vision-language models
  through MLX, and smaller local models where they are enough. Nothing calls out at run time.
- Research, then measure, then build. Each part starts with a short study of the options,
  tested on these documents, and ends in a decision recorded here.
- The golden dataset comes before the implementation: hand-checked labels and an eval harness
  that scores any version of a part, so every change is measured.
- Built test-first (TDD) on a hexagonal architecture (ports and adapters). The core logic depends
  only on ports, small interfaces. Each model, file format or store is an adapter behind one of them, so
  it can be swapped without touching the core.

## Routing research

Chose a layered router: structure rules on the file, then a DINOv2-small probe at 90%
confidence, then Qwen3-VL 8B for the rest. On 244 labelled requests it made 0 mistakes on the
224 with a case, sent 2.5% to 3.9% of files to the model, and cost 34 ms median per file.

- Tried: PDF structure, pixel and EXIF rules; linear probes on DINOv2, CLIP, SigLIP 2 and Docling
  features; zero-shot CLIP and SigLIP 2; Qwen3-VL 2B to 8B; LiquidAI d1 decision models.
- Failed: pixel and EXIF rules send phone photos of drawings to the photo case. The probe alone
  sends reports and logos to the drawing case.
- Open: the probe's image model, the 0.9 threshold and the answer for a file that fits no case
  all need the customer's files.

Write-up: `research/routing/README.md`.

## Drawing-to-JSON research

Chose to find each callout from the PDF's vector paths, then read one crop at a time with
Qwen3-VL 8B. Every annotation on these NIST PDFs is pure blue, so PyMuPDF boxes all of them
with no model in 33 s for 30 pages. On 8 test crops the 8B passed 42 of 46 checks and named
all 6 GD&T symbols, at 5 s per crop. The whole page to the same model is the baseline.

- Tried: the PDF tags and structure, Docling, RapidOCR, Qwen3-VL 4B and 8B on whole pages and
  on crops, MechVL-4B SFT and RL, and OCR text as a prompt hint.
- Failed: Docling turns the drawing into one picture. OCR loses every GD&T symbol. The whole
  page loops and misreads digits on dense sheets. MechVL scores below plain Qwen3-VL 4B.
- Open: grouping merges close callouts on dense sheets, no model reads the counterbore or depth
  symbols, and drawings that are not blue or are scanned are untested.

Write-up: `research/drawing/README.md`.

## Eval harness

`uv run evals` scores any reader version against the gold labels and stores every run, so two
versions can be compared on the same cases. The text-layer reader, which needs no model, sets the
floor:

| Metric (all gold) | Value |
| --- | --- |
| F1 | 0.344 |
| Precision | 0.902 |
| Recall | 0.213 |
| Partial-gold recall | 0.129 |

- How: a value matches on page, unit, kind and number. Only 4 drawings are labelled in full
  (full gold). The other 7 have about 10 values each (partial gold), so they give recall only.
  Without them the test split would hold 2 drawings.
- Why the text layer is the floor: it reads the title block and notes, which are real PDF text.
  Most callouts are drawn as vector paths, so it misses them. A real reader must raise recall
  without giving up much precision.
- Traces: each call is stored under its request id; `resourcly request` prints it.

Details: `docs/evals.md`.

## Label screen

The label screen is for reviewing and extending the gold, not for making it from scratch.
The gold was drafted from crops and overlays; the screen is where a person checks each value
against the page, fixes it, and approves it, or adds a value that was missed.

- How: `uv run resourcly annotation-ui` shows each page with a numbered box per value and a form
  beside it. The screen uses only the gold endpoints. The code is in `src/frontend/annotation`, and
  the chat screen sits beside it in `src/frontend/chat`.
- How saves stay safe: nothing is written until Save. The server validates the whole document
  against the gold models and refuses an invalid one, listing the issues. A valid one is written
  to a temporary file and then swapped in, so a file is never half written. Every change is
  then a plain git diff to review before it is committed.

How to use it: `docs/label-screen.md`.

## Agent API

The chat is one HTTP API, made for a later chat screen; the CLI calls the same services.

- One message is one request: text, files, or both. Many files in one message is a bulk upload.
  Each file is an item with its own case, status and result.
- `POST /api/requests` returns 202 with the request record at once. One background worker routes
  every item, then reads the drawings one at a time, and the client polls the record. A read can
  take minutes with a vision model, so a held request would time out.
- The record holds what a chat screen shows: status, progress, reply or error per item,
  and the drawing JSON beside it.
- Each step is written to the trace store when it ends, not when the request ends, so a live
  trace stream can be added without changing the agent.
- The router is `three-layer-v1` (see "The router"). Photos and text questions get a "not
  available yet" reply, so an answerer can be swapped in later without changing the shape.
- The request store and the worker sit behind ports: at scale they become a database and a queue.

How to use it: `docs/usage.md`.

## Chat screen

The chat screen is the agent API in a browser. It is its own app in `src/frontend/chat`, beside
the label screen, and shares no code with it.

- How: `uv run resourcly serve` serves the built screen and the API on one port. One message is
  one request, and the screen polls the requests while any of them works. Each file's card shows
  the route, the layer that chose it, how sure it was and why, and the page with its values.
- The viewer: a file opens with its page beside its JSON. Each value has a numbered box, and the
  box and the JSON entry are linked both ways, so a person can check every value against the
  drawing. The trace tab lists each router layer's verdict under the routing step.
- The page comes from `GET /api/requests/<id>/items/<item>/pages/<n>.png`. Uploads are kept as
  PDFs, a photo as a one-page PDF, so the one endpoint serves both.
- What comes next: a live trace stream in place of the polling, and real answers for photos and
  text questions.

How to use it: `docs/chat-ui.md`.

## One harness for every use case

The router and the failure finder are scored by the same harness as the reader. Each is one more
component with one suite in `suites.py`: gold cases, a version file, a score per case, a stored
run and a comparison. The model-free versions set the floors, on the dev split:

| Version | Cases | Primary | Other |
| --- | --- | --- | --- |
| router `stub-v0` | 123 | accuracy 0.602 | drawing recall 0.120, other kept out 0.500 |
| failure `shuffled-v0` | 86 | section@1 0.038 | mode@3 0.769, kept out 0.000 |

- How: the router gold is the 244 requests of the routing research, moved to `evals/gold/routes`.
  The failure gold is 3 perturbed copies of each of the 46 report figures, plus 11 drawings and
  5 unrelated images that should match nothing.
- Why the floors are low: the stub router calls every image a photo, so it misses drawings sent
  as pictures. The shuffled finder gives the same order for every photo and never keeps one out.

Details: `docs/evals.md`.

## Versions

Each component runs a named version: a file in `versions/` that picks the code (`impl`) and gives
it its settings. The app and the evals load the same file the same way, so a score always belongs
to the exact recipe the app would serve.

- Why files, not code: trying a new prompt, model or threshold is a new file, not a code change.
  Old files stay, so an old run still says what it measured.
- Why a hash: a run stores the version's hash, which covers its settings and any file it names,
  such as the router's probe. `evals compare` warns when a version changed after its run.
- Why it refuses to load: with an unknown `impl` or setting, or a missing file, the app and the
  evals both refuse the version rather than run something other than what was scored.
- How a version ships: score it, compare it with the current one, then make it the default.
  `RESOURCLY_<COMPONENT>_VERSION` picks another without a code change, and each trace step names
  the version that served it.

Details: `versions/README.md`.

## The router

`three-layer-v1`, the default: structure rules, a DINOv2-small probe over drawing, photo and
other deciding at 0.9, then Qwen3-VL 8B. The probe trained on the train split only (37 drawings,
23 photos, 2 other).

| Version | Split | Accuracy | Drawing recall | Other kept out |
| --- | --- | --- | --- | --- |
| `stub-v0` | dev (123) | 0.602 | 0.120 | 0.500 |
| `three-layer-v1` | dev (123) | 0.992 | 1.000 | 0.833 |
| `stub-v0` | test (57) | 0.421 | 0.091 | 0.500 |
| `three-layer-v1` | test (57) | 1.000 | 1.000 | 1.000 |

- How: `evals run`, then `evals compare` with `stub-v0`. Accuracy counts other files too.
- Other class: the probe now keeps 3 dev report pages out itself, so 18 dev files reach Qwen3-VL,
  not 23. A dimensioned physics diagram still goes to drawing (probe 0.989).
- Honest reading: near-perfect scores mean the route set is easy. Its phone photos and scans are
  made by code; it has no real ones and no mixed pages.
- Limits: one NIST drawing family in every split. `stub-v0` needs no model.

Details: `docs/routing.md`.

## Drawing reader

Chose `vector-crop-v2`: find each callout from the PDF's vector paths with no model, then
Qwen3-VL 8B reads one crop at a time; `whole-page-v1` sends whole pages.

| Version | Split | F1 | Recall | Partial recall |
| --- | --- | --- | --- | --- |
| `whole-page-v1` | all | 0.650 | 0.672 | 0.543 |
| `vector-crop-v1` | all | **0.725** | **0.862** | **0.743** |
| `whole-page-v1` | dev | **0.757** | 0.812 | 0.633 |
| `vector-crop-v1` | dev | 0.739 | **0.917** | **0.867** |

- Trade-off: vector-crop wins on all gold (F1 0.725 against 0.650); whole-page wins on dev
  (0.757 against 0.739), where only CTC-01 and FTC-07 page 2 have full gold.
- Raster pages: `vector-crop-v1` reads nothing from a page with no vector paths, such as a scan or
  an image upload (0 values). `vector-crop-v2` reads that page whole, as `whole-page-v1` does; a
  CTC-01 page sent as a PNG gives 15 values. On the NIST PDFs, whose every page has vector
  callouts, v2 is v1 (its runs are pending).
- Answers: each is checked as a typed Pydantic model; one with no JSON or the wrong shape reads
  as nothing and counts as an issue of the reading.
- Weak spot: precision 0.625 (whole-page 0.629); frame cells are read again as bare numbers.
- Cost: 64 s per page against 36.

Details: `experiments/drawing/README.md`.

## Drawing JSON for the 11 drawings

`outputs/<drawing>.json` is what `vector-crop-v1` returns for each NIST drawing, from the run on
all gold. Each file is in the gold schema and passes its checks.

| Measure | Value |
| --- | --- |
| Pages read | 30, in 32 minutes (64 s per page, model load included) |
| Errors, schema issues | 0 of 11, 0 |
| Values written | 984, each with page, box, kind, value, limits and meaning |
| Partial-gold recall | 0.743 (FTC-09 1.0, CTC-05 and FTC-10 0.5) |
| Full-gold F1 | 0.725 |

- Known precision issues: frame cells read again as bare numbers, a two-line note split in two,
  and a neighbouring callout's cut-off text read as a value. On FTC-07 a modifier written as text
  ("⌀.06 M") is kept as a separate diameter.
- `confidence` is null: no reader measures how sure it is, so it writes nothing rather than a
  made-up number.
- Each callout is one feature typed by a fixed rule; leaders are not traced.
- Rerun: `uv run --extra vlm evals run reader --version vector-crop-v1 --split all`, then
  `04_winner_outputs.ipynb`. Decoding is greedy, so a rerun gives the same files.

## Fault detection and chat research

Chose DINOv2-base alone to find the closest report figures, then Qwen3-VL 8B to write a cited answer
from the top 3 figures and their report text. With the source figure hidden, DINOv2 put the
right report first for 95.7% of 138 perturbed report figures and the right failure mode in the
top 3 for 94.2%, the best of the signals compared, in under 0.1 s per photo.

- Tried: SigLIP 2 image and caption vectors, DINOv2, their rank fusions, five ways to feed a
  non-square photo, a similarity gate, and Qwen3-VL 8B end to end.
- Failed: caption vectors drag the fusion down. The router's DINOv2-small is worse on every
  held-out score (report@1 90.6%, mode@3 90.6%), so it is not shared. On 3 end-to-end cases the
  model rejected the right figure every time and took about 2 minutes each.
- Open: the answer step and the chat need a scored question set; the 0.28 gate floor rests on
  12 unrelated photos; the router's probe has not been tried on DINOv2-base.

Write-up: `research/failure/README.md`.

## Photo answers

`dinov2-base-v1` finds the report figures nearest a photo; `photo-v2` has Qwen3-VL 8B answer from
the closest 3 in one call. Code keeps only findings citing what it was shown, a "stated" action
must quote a report paragraph, and a photo the model calls unrelated is kept out. Both are the
defaults; the answer shares the reader's Qwen adapter.

| Version | Split | Section@1 | Mode@3 | Kept out |
| --- | --- | --- | --- | --- |
| `dinov2-base-v1` | dev / test | 1.000 / 1.000 | 1.000 / 1.000 | 0.375 / 0.250 |
| `dinov2-small-v1` | dev / test | 1.000 / 1.000 | 1.000 / 1.000 | 0.000 / 0.125 |

- Honest reading: gold photos are copies of indexed figures. Held out, base gets the report first
  for 95.7%, small 89.9%.
- Gate: it does not hold on real photos of other parts; 10 of 12 pass 0.28.
- Answers: a stored 6-photo spot check, 4 right; the 18-photo before and after is pending.

Details: `docs/photo-answers.md`, `evals/photo-answers/`.
