# How to read the project

Seven short steps, about 30 minutes. The models for step 6 are over 6 GB, so start its setup first.

## 0. The map (2 minutes)

Each task item of [INSTRUCTIONS.md](INSTRUCTIONS.md). Code is under `src/resourcly/`.

| Item | Built in | Measured by | Status |
| --- | --- | --- | --- |
| 1 Input | `agent.py`, `api.py` | tests | Done; text questions get "not available yet" |
| 2 Picture | `answers.py`, `adapters/nearest_figures.py` | `failure`, `answer` evals | Finder mode@3 0.942; answer 0.625 on 8 cases |
| 3 Drawing | `adapters/vlm_readers.py`, [outputs/](outputs) | `reader` eval | F1 0.725, precision 0.625 |
| 4 Automatic | `adapters/route_*.py` | `router` eval | Accuracy 0.992 dev, 1.000 test, on an easy set |
| 5 Bulk upload | `agent.py` | tests | Done; one worker, files in turn |
| 6 Private | `adapters/mlx_vlm_model.py` | tests | Models load from the local cache only |
| 7 Scale | stores and worker behind `ports.py` | not measured | Design only |
| 8 Tracking | `adapters/sqlite_trace.py` | tests | Done |
| 9 Validation | `eval_harness/` | its own tests | 4 parts; no whole-agent score |

## 1. The research (8 minutes)

Read each README, then open its `review.html` in a browser for the results and pictures.

| Folder | Takeaway |
| --- | --- |
| [research/routing](research/routing/README.md) | Cheapest layer first: rules, a DINOv2-small probe, then Qwen3-VL 8B. |
| [research/drawing](research/drawing/README.md) | Callouts are pure blue vector paths, so code finds them; the model reads one crop at a time. |
| [research/schema](research/schema/README.md) | A flat list of values, each pointing to a feature. |
| [research/failure](research/failure/README.md) | DINOv2-base finds the right report 95.7% of the time; the answer is the open half. |

## 2. The decisions (4 minutes)

[NOTES.md](NOTES.md): per part, what was tried, what failed, the numbers and what is open.

## 3. The structure (3 minutes)

```text
message -> agent: one request, one item per file
  item -> router: structure rules -> DINOv2-small probe -> Qwen3-VL 8B
    drawing     -> reader (vector-crop-v2)       -> JSON of every value
    photo       -> fault finder (dinov2-base-v1) -> photo answer (photo-v2)
    text, other -> a fixed reply
  every step -> trace store, under the request id
```

Models and stores are adapters behind `ports.py`. Each part runs a version file:
[versions/README.md](versions/README.md).

## 4. The measuring (4 minutes)

Read [the eval harness README](src/resourcly/eval_harness/README.md), then compare two fault
finders. This takes seconds and needs only DINOv2-base.

```sh
uv run evals run failure --version shuffled-v0
uv run evals run failure --version dinov2-base-v1
make compare COMPONENT=failure A=shuffled-v0 B=dinov2-base-v1
# (uv run evals compare failure shuffled-v0 dinov2-base-v1)
```

Section@1 goes from 0.038 to 0.564 on dev. All numbers: [docs/evals.md](docs/evals.md).

## 5. The code (5 minutes)

| Part | Files, in order |
| --- | --- |
| Router | `services.py` (`RouterService`), `adapters/route_structure.py`, `adapters/route_probe.py` |
| Reader | `adapters/callout_locator.py`, `adapters/vlm_readers.py`, `callout_values.py` |
| Photo | `adapters/nearest_figures.py`, `answers.py`, `adapters/vlm_answer.py` |
| Agent and API | `agent.py`, `api.py`, `bootstrap.py` |

Tests: `make test` (`uv run pytest`).

## 6. Run it (4 minutes, plus model time)

```sh
make setup   # (scripts/setup.sh): packages, models, the screen build
make serve   # (uv run resourcly serve), then open http://127.0.0.1:8000
```

The chat opens with two demo chats, answered before, that show results with no model
([demo/README.md](demo/README.md)). Then try:

| Try | Send |
| --- | --- |
| A drawing | `data/drawings/nist_ctc_01_asme1_rd.pdf`, about a minute |
| A photo | `evals/gold/failure/images/pos_18-061_fig05_v0.jpg` |
| A bulk upload | CTC-01, CTC-03, CTC-04 and the photo together |
| A trace | Open a file, then its Trace tab |

Setup details: [docs/setup.md](docs/setup.md). Terminal and no-model use:
[README.md](README.md#run-each-part).

## Known limits

- Text questions are not answered yet.
- Test photos and scans are made by code ([routing](docs/routing.md#limits),
  [photo answers](NOTES.md#photo-answers)).
- The photo gate lets drawings and most real photos of other parts through.
- The answer eval has 8 cases, and the `photo-v2` and `vector-crop-v2` runs are pending
  ([docs/evals.md](docs/evals.md#current-numbers)).
- All drawings come from one NIST family.
