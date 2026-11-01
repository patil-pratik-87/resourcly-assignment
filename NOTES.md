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
| Strict F1 | 0.344 |
| Strict precision | 0.902 |
| Strict recall | 0.213 |
| Partial-gold recall | 0.129 |

- How: a value matches on page, unit, kind and number. Only 4 drawings are labelled in full
  (full gold). The other 7 have about 10 values each (partial gold), so they give recall only.
  Without them the test split would hold 2 drawings.
- Why the text layer is the floor: it reads the title block and notes, which are real PDF text.
  Most callouts are drawn as vector paths, so it misses them. A real reader must raise recall
  without giving up much precision.
- Traces: each call is stored under its request id; `evals show --request` prints it.

Details: `docs/evals.md`.

## Label screen

The label screen is for reviewing and extending the gold, not for making it from scratch.
The gold was drafted from crops and overlays; the screen is where a person checks each value
against the page, fixes it, and approves it, or adds a value that was missed.

- How: `uv run resourcly annotation-ui` shows each page with a numbered box per value and a form
  beside it. The screen uses only the gold endpoints. The code is in `src/frontend/annotation`, so
  the chat screen can sit beside it later.
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
- The router is the model-free `stub-v0`. Photos and text questions get a "not available yet"
  reply, so an answerer can be swapped in later without changing the shape.
- The request store and the worker sit behind ports: at scale they become a database and a queue.

How to use it: `docs/usage.md`.
