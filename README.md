# Resourcly Document Agent

New here? Start with [HOW_TO_READ.md](HOW_TO_READ.md), a 30 minute path through the project.

A chat agent for technical documents that runs fully on one Mac. You send text, files or both, and
the agent routes each file itself. A technical drawing comes back as JSON with every value on it,
what it belongs to and what it means. A photo of a failed part gets what is wrong and what to do
from the three NTSB reports, each fact cited. A text question alone is told text answers are not
available yet, and a file that fits no case is told so. Every step of every
request is stored, and an eval harness scores each part.

## Quick start

On an Apple silicon Mac (16 GB of memory, about 15 GB of free disk):

```sh
make setup   # the only online step: packages, models, the Agents UI, a check
make run     # set up once (downloads and builds), then serve the Agents UI on http://127.0.0.1:8000
```

If `make setup` ends by saying uv is not on your PATH, add the line it prints to `~/.zshrc`, so
the `uv run` commands below work in a new shell.

Open [http://127.0.0.1:8000](http://127.0.0.1:8000) and drop a drawing from `data/drawings/` into it. After setup, nothing
reaches the network. `make doctor` prints each problem and its fix. Details:
[docs/setup.md](docs/setup.md).

![A drawing read in the Agents UI: each value boxed on the page and linked to its JSON](docs/img/chat-ui/linked-view.png)

![A photo of a spar cap answered from the NTSB reports, each fact cited](docs/img/chat-ui/photo-answer.png)

## Run each part

### The chat

In the Agents UI, type a message, attach or drop files, and press Enter. Each file gets a card
with its case, the reason and its result ([docs/chat-ui.md](docs/chat-ui.md)). It opens with two
demo chats answered before, a drawing and a photo; `serve --no-demo` leaves them out, and
`--port 8123` picks another port. From a terminal:

```sh
uv run resourcly ask "read this" --file data/drawings/nist_ctc_01_asme1_rd.pdf
uv run resourcly ask --file crack.jpg   # a photo of a part
```

`ask` waits for every file, prints the results, and exits with 1 if any failed. A drawing page
takes about a minute, a photo 25 s. The HTTP API: [docs/chat-ui.md](docs/chat-ui.md#the-api).

### A bulk upload

Attach or drop many files in one message. From a terminal, `--file` repeats and takes a folder,
and `--out` writes each drawing's JSON:

```sh
uv run resourcly ask --file data/drawings --out out/drawings
```

### Looking up a request

```sh
uv run resourcly requests        # the latest requests, newest first
uv run resourcly request <id>    # each item, then every step and what it called
```

In the Agents UI, the Requests tab shows a file beside its JSON, and its Trace tab the same steps.

### Validating a new version: the eval harness

The eval harness has one suite per part: reader, router, failure, failure-copy and answer. It runs
a version on the gold cases in `evals/gold/`, stores every run in `runs/evals.sqlite`, and
`compare` says whether a new version is better or worse, by metric and by case. Each part's
settings are a version file, `versions/<part>/<name>.toml`
([versions/README.md](versions/README.md)). Copy one, edit it, run both on the same sample, and
compare:

```sh
cp versions/reader/vector-crop-v2.toml versions/reader/my-reader-v3.toml   # then edit it
uv run evals run reader --version vector-crop-v2 --limit 10   # prints "run <base id>"
uv run evals run reader --version my-reader-v3 --limit 10     # prints "run <new id>"
make compare COMPONENT=reader A=<base id> B=<new id>
```

`--limit 10` picks the same seeded sample each time; after a full dev run, `compare` takes version
names. `make evals-quick` runs 10 dev cases of every suite. How it works:
[src/resourcly/eval_harness/README.md](src/resourcly/eval_harness/README.md); the numbers:
[docs/evals.md](docs/evals.md).

### Reviewing the gold by hand

A person reviews and corrects the eval gold in `evals/gold/` on the label screen: each value boxed
on its page, with a form to fix or approve it. Each save is a `git diff`
([docs/label-screen.md](docs/label-screen.md)).

```sh
(cd src/frontend/annotation && npm ci && npm run build)
uv run resourcly annotation-ui
```

## Settings

| Variable                                                | Default                            |
| ------------------------------------------------------- | ---------------------------------- |
| `RESOURCLY_READER_VERSION`, `RESOURCLY_ROUTER_VERSION`  | `vector-crop-v2`, `three-layer-v1` |
| `RESOURCLY_FAILURE_VERSION`, `RESOURCLY_ANSWER_VERSION` | `dinov2-base-v1`, `photo-v2`       |
| `RESOURCLY_MAX_UPLOAD_BYTES`, `RESOURCLY_MAX_FILES`     | 50 MB, 50                          |

Without the models, these run on any machine, with less: the text layer, routing by file type,
and figure captions as a photo's answer.

```sh
RESOURCLY_READER_VERSION=textlayer-v0 RESOURCLY_ROUTER_VERSION=stub-v0 \
  RESOURCLY_FAILURE_VERSION=shuffled-v0 RESOURCLY_ANSWER_VERSION=captions-v0 uv run resourcly serve
```

## The parts

| Part           | Default                                                                                 | Measured                                                                                | Doc                                                  |
| -------------- | --------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------- | ---------------------------------------------------- |
| Router         | `three-layer-v1`: rules, a DINOv2-small probe, then Qwen3-VL 8B                         | accuracy 0.992 on 123 dev files, 1.000 on 57 test                                       | [docs/routing.md](docs/routing.md)                   |
| Drawing reader | `vector-crop-v2`: each callout from the vector paths read by Qwen3-VL 8B                | as `vector-crop-v1` on these PDFs: F1 0.725, recall 0.862 on the 11 drawings            | [experiments/drawing](experiments/drawing/README.md) |
| Fault finder   | `dinov2-base-v1`: the report figures nearest the photo                                  | section@1 0.645, mode@3 0.942 on 154 held-out cases                                     | [research/failure](research/failure/README.md)       |
| Photo answer   | `photo-v2`: Qwen3-VL 8B answers from the 3 closest figures, keeping only cited findings | hand check 4 of 6 right; `photo-v1` correct 0.625 on 8 dev cases; no real photos tested | [NOTES.md](NOTES.md#photo-answers)                   |
| Agent and API  | a request per message, traced                                                           | not scored as a whole                                                                   | [docs/chat-ui.md](docs/chat-ui.md#the-api)           |

## Out of scope

Left out because of the time limit:

- **Text answering.** A text question alone gets a fixed reply, and text sent with a drawing does
  not change its JSON; only a photo uses the text as its question. Answering from the reports with
  citations may come later.
- **The changes for scale.** The design for more than a million documents (a vLLM model server,
  a job queue with workers, Postgres and object storage, a nearest neighbour index, a cache for
  repeated files) is written up in [docs/privacy-and-scale.md](docs/privacy-and-scale.md), not
  built. Today everything runs on one Mac, one request at a time.

## Where things are

| Path                                                   | What it holds                                                                       |
| ------------------------------------------------------ | ----------------------------------------------------------------------------------- |
| `outputs/`                                             | The JSON of the 11 drawings ([NOTES.md](NOTES.md#drawing-json-for-the-11-drawings)) |
| `evals/`                                               | The gold cases, their splits, and the photo answers' hand checks                    |
| `versions/`                                            | Every version of every part, with the probe and figure indexes                      |
| `demo/`                                                | The two demo chats ([demo/README.md](demo/README.md))                               |
| `research/`, `experiments/`                            | The research behind each part                                                       |
| `src/`                                                 | The code; the two screens are in `src/frontend/`                                    |
| `docs/`                                                | Setup, the Agents UI and API, the label screen, routing, evals                      |
| [NOTES.md](NOTES.md)                                   | What was tried, measured and chosen, and why                                        |
| [HOW_TO_READ.md](HOW_TO_READ.md) | How to read the project, in 30 minutes |
| [docs/privacy-and-scale.md](docs/privacy-and-scale.md) | How the design keeps data private and scales                                        |

`make test` runs ruff, pytest and the Agents UI tests.
