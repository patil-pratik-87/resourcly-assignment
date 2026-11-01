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

## 2026-11-01: Routing research

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
