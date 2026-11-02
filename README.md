# Resourcly case study

A chat agent for technical documents that runs fully on one Mac. You send text, files or both and
never say what you want: the agent routes each file itself. A technical drawing comes back as JSON
with every value on it, what it belongs to and what it means. A photo of a failed part gets what is
wrong and what to do from the three NTSB reports, each fact cited. A text question alone gets a
reply that text answers are not available yet, and a file that fits no case, such as a whole
report, gets a reply that says so. Every step of every request is stored, and an eval harness
scores each part on gold cases.

## Quick start

On an Apple silicon Mac (16 GB of memory, about 15 GB of free disk):

```sh
make setup   # the only online step: packages, models, the Agents UI, then a check
make run     # set up once (downloads and builds), then serve the Agents UI on http://127.0.0.1:8000
```

Open http://127.0.0.1:8000 and drop a drawing from `data/drawings/` into the Agents UI. After
setup, nothing reaches the network. `make doctor` prints each problem with the command that fixes
it. Details: [docs/setup.md](docs/setup.md).

## Run each part

### The chat

In the Agents UI, type a message, attach files with the clip or drop them anywhere, and press
Enter. Each file gets a card with its case, why the router chose it, and its result
([docs/chat-ui.md](docs/chat-ui.md)). `uv run resourcly serve --host 0.0.0.0 --port 8123` serves it
elsewhere. From a terminal:

```sh
uv run resourcly ask "read this" --file data/drawings/nist_ctc_01_asme1_rd.pdf
uv run resourcly ask "why did this spar crack?" --file crack.jpg
uv run resourcly ask "why did the bracket crack?"
```

`ask` waits until every file is handled, prints each result, and exits with 1 if any file failed.
A drawing takes about a minute per page and a photo about 25 s. Over HTTP, `POST /api/requests`
answers at once and the client polls ([the API](docs/chat-ui.md#the-api)).

### A bulk upload

In the Agents UI, attach or drop many files in one message; a line over the cards counts their
states. From a terminal, `--file` repeats and takes a folder, and `--out` writes each drawing's
JSON:

```sh
uv run resourcly ask --file data/drawings --out out/drawings
```

A message takes at most 50 files and 50 MB per file.

### Looking up a request

```sh
uv run resourcly requests        # the latest requests, newest first
uv run resourcly request <id>    # each item, then every step: what it called, with what, how long
```

In the Agents UI, the Requests screen opens one file beside its JSON, and its Trace tab lists the
same steps, with every router layer's verdict.

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

`--limit 10` picks the same seeded sample each time. `compare` shows each metric, the change, a
verdict, and the cases that changed. Without `--limit` a run covers the dev split, and `compare`
takes version names. `make evals-quick` runs 10 dev cases of every suite
([docs/evals.md](docs/evals.md)).

## Settings

| Variable | Default |
| --- | --- |
| `RESOURCLY_READER_VERSION`, `RESOURCLY_ROUTER_VERSION` | `vector-crop-v2`, `three-layer-v1` |
| `RESOURCLY_FAILURE_VERSION`, `RESOURCLY_ANSWER_VERSION` | `dinov2-base-v1`, `photo-v2` |
| `RESOURCLY_UPLOADS_DIR`, `RESOURCLY_TRACE_DB` | `var/uploads`, `var/traces.sqlite` |
| `RESOURCLY_MAX_UPLOAD_BYTES`, `RESOURCLY_MAX_FILES` | 50 MB, 50 |

On a machine without the models, these versions need none: the text layer reads only the title
block and notes, the stub routes by file type, and a photo gets the closest figures' captions.

```sh
RESOURCLY_READER_VERSION=textlayer-v0 RESOURCLY_ROUTER_VERSION=stub-v0 \
  RESOURCLY_FAILURE_VERSION=shuffled-v0 RESOURCLY_ANSWER_VERSION=captions-v0 uv run resourcly serve
```

## The parts

| Part | Default | Measured | Doc |
| --- | --- | --- | --- |
| Router | `three-layer-v1`: structure rules, a DINOv2-small probe, then Qwen3-VL 8B | accuracy 0.992 on 123 dev files, 1.000 on 57 test files (`stub-v0`: 0.602, 0.421) | [docs/routing.md](docs/routing.md) |
| Drawing reader | `vector-crop-v2`: each callout from the vector paths read by Qwen3-VL 8B | as `vector-crop-v1` on these PDFs: F1 0.725, recall 0.862 on the 11 drawings | [experiments/drawing](experiments/drawing/README.md) |
| Fault finder | `dinov2-base-v1`: the report figures nearest the photo | section@1 0.645, mode@3 0.942 on 154 held-out cases | [research/failure](research/failure/README.md) |
| Photo answer | `photo-v2`: Qwen3-VL 8B answers from the closest figures | hand check 4 of 6 right; `photo-v1` correct 0.625 on 8 dev cases | [docs/photo-answers.md](docs/photo-answers.md) |
| Agent and API | a request per message, a background worker, a trace per step | not scored as a whole yet | [docs/chat-ui.md](docs/chat-ui.md#the-api) |
| Eval harness | suites: reader, router, failure, failure-copy, answer | | [docs/evals.md](docs/evals.md) |

## Where things are

| Path | What it holds |
| --- | --- |
| `outputs/` | The JSON of the 11 drawings ([NOTES.md](NOTES.md#drawing-json-for-the-11-drawings)) |
| `evals/` | The gold cases, their splits, and the photo answers' hand checks |
| `versions/` | Every version of every part, with the committed probe and figure indexes |
| `research/`, `experiments/` | The research behind each part, and the reader notebooks |
| `src/` | The agent, API, CLI and eval harness, and the screens in `src/frontend/` |
| `docs/` | Setup, the Agents UI and API, routing, photo answers, evals |
| [NOTES.md](NOTES.md) | What was tried, measured and chosen, and why |
| [REVIEWING.md](REVIEWING.md) | A guide for reviewing this work |
| [docs/privacy-and-scale.md](docs/privacy-and-scale.md) | How the design keeps data private and scales |

`make test` runs ruff, pytest and the Agents UI's tests.
