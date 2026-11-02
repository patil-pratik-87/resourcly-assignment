# Resourcly case study

A chat agent for technical documents that runs fully on one Mac. You send text, files or both,
and never say what you want: the agent routes each file itself. A technical drawing comes back as
JSON with every value on it, what it belongs to and what it means. A photo of a failed part gets
what is wrong and what to do, from the three NTSB reports, with each fact cited. A text question
alone gets a reply that text answers are not available yet, and a file that fits no case, such as
a whole report, gets a reply that says so. Every request and every step it took is stored, and an
eval harness scores each part on gold cases.

## Quick start

On an Apple silicon Mac (16 GB of memory, about 15 GB of free disk):

```sh
make setup   # the only online step: packages, models, chat screen, then a check
make run     # serves the chat on http://127.0.0.1:8000
```

Open http://127.0.0.1:8000 and drop a drawing from `data/drawings/` into the chat. After setup,
nothing reaches the network: the models load from the local cache only. When something is wrong,
`make doctor` prints each problem with the command that fixes it. Details: [docs/setup.md](docs/setup.md).

## Run each part

### The chat

```sh
make run
```

Type a message, attach files with the clip or drop them anywhere, and press Enter. Each file gets
a card with its case, why the router chose it, and its result. The same from a terminal:

```sh
uv run resourcly ask "read this" --file data/drawings/nist_ctc_01_asme1_rd.pdf
```

How to use the screen: [docs/chat-ui.md](docs/chat-ui.md). The CLI and the HTTP API:
[docs/usage.md](docs/usage.md).

### A bulk upload

In the chat, attach or drop many files in one message; a line over the cards counts their states.
From a terminal, `--file` repeats and also takes a folder; `--out` writes each drawing's JSON:

```sh
uv run resourcly ask --file data/drawings --out out/drawings
```

### Looking up a request

```sh
uv run resourcly requests        # the latest requests, newest first
uv run resourcly request <id>    # each item, then every step: what it called, with what, how long
```

In the chat, the Requests screen opens one file beside its JSON, and its Trace tab lists the same
steps, with every router layer's verdict.

### Validating a new version

Each part's settings live in a version file, `versions/<part>/<name>.toml`
([versions/README.md](versions/README.md)). Copy one, edit it, run it on the same sample as the
current one, and compare:

```sh
cp versions/reader/vector-crop-v2.toml versions/reader/my-reader-v3.toml   # then edit it
uv run evals run reader --version vector-crop-v2 --limit 10   # prints "run <base id>"
uv run evals run reader --version my-reader-v3 --limit 10     # prints "run <new id>"
make compare COMPONENT=reader A=<base id> B=<new id>
```

`--limit 10` picks the same seeded sample each time. `compare` shows each metric, the change and a
verdict, and which cases got better or worse. Without `--limit` a run covers the whole dev split,
and `make compare` then takes version names. `make evals-quick` runs 10 dev cases of every suite
with the default versions. How the harness works: [docs/evals.md](docs/evals.md).

## The parts

| Part | Default version | Measured | Doc |
| --- | --- | --- | --- |
| Router | `three-layer-v1`: structure rules, a DINOv2-small probe, then Qwen3-VL 8B | accuracy 0.992 on 123 dev files, 1.000 on 57 test files (`stub-v0`: 0.602, 0.421) | [docs/routing.md](docs/routing.md) |
| Drawing reader | `vector-crop-v2`: callouts found from the PDF's vector paths, each crop read by Qwen3-VL 8B | `vector-crop-v1`, the same on these PDFs: F1 0.725, recall 0.862 on the 11 drawings | [experiments/drawing/README.md](experiments/drawing/README.md) |
| Fault finder | `dinov2-base-v1`: the report figures nearest the photo | section@1 0.645, mode@3 0.942 on 154 held-out cases | [research/failure/README.md](research/failure/README.md) |
| Photo answer | `photo-v2`: Qwen3-VL 8B answers from the closest figures, each fact cited | hand check: 4 of 6 photos right; `photo-v1` correct 0.625 on 8 dev cases | [docs/photo-answers.md](docs/photo-answers.md) |
| Agent and API | one request per message, a background worker, a trace of every step | not scored as a whole yet | [docs/usage.md](docs/usage.md) |
| Eval harness | five suites: reader, router, failure, failure-copy, answer | | [docs/evals.md](docs/evals.md) |

The models: Qwen3-VL 8B 4-bit through MLX on the Mac's GPU, and DINOv2 small and base through
PyTorch. All run locally. On a machine without them, `RESOURCLY_READER_VERSION=textlayer-v0`,
`RESOURCLY_ROUTER_VERSION=stub-v0` and `RESOURCLY_ANSWER_VERSION=captions-v0` need no model.

## Where things are

| Path | What it holds |
| --- | --- |
| `outputs/` | The JSON of the 11 drawings, one file each ([NOTES.md](NOTES.md#drawing-json-for-the-11-drawings)) |
| `evals/` | The gold cases, their splits, and the photo answers' hand checks |
| `versions/` | Every version of every part, and the committed probe and figure indexes |
| `research/` | The research behind each part: routing, drawings, the JSON schema, failures |
| `experiments/` | The notebooks that compared the drawing readers |
| `src/resourcly/` | The agent, its API and CLI, and the eval harness; `src/frontend/` holds the screens |
| `docs/` | How to set up, use and measure each part |
| [NOTES.md](NOTES.md) | What was tried, measured and chosen, and why |
| [REVIEWING.md](REVIEWING.md) | A guide for reviewing this work |
| [docs/privacy-and-scale.md](docs/privacy-and-scale.md) | How the design keeps data private and scales |

## Tests

```sh
make test    # ruff, pytest and the chat screen's tests
```
