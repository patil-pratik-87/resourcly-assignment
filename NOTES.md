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
