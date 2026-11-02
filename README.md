# Resourcly case study

A chat agent for technical documents: it decides the case for each file, reads technical drawings
into JSON, and stores what it did for every request.

## Quick start

On an Apple silicon Mac:

```sh
make run          # set up once (downloads and builds), then serve the chat on http://127.0.0.1:8000
make evals-quick  # score 10 dev cases of each component
```

Setup is the only online step; after it everything runs offline. What it does, the other `make`
targets, and `make doctor` when something is wrong: [docs/setup.md](docs/setup.md).

## Use it

```sh
uv run resourcly ask "read this" --file data/drawings/nist_ctc_01_asme1_rd.pdf
```

The models run locally and are downloaded once, by the setup. Drawings are read by
`vector-crop-v2` with Qwen3-VL 8B on Apple silicon; a scan or an image is read a whole page at a
time. On a machine without the models, set `RESOURCLY_READER_VERSION=textlayer-v0` (the text
layer only) and `RESOURCLY_ROUTER_VERSION=stub-v0`, which need no model.

How to chat, send many drawings at once, and look up a request, from the CLI or over HTTP:
[docs/usage.md](docs/usage.md). The same in a browser, with `uv run resourcly serve`:
[docs/chat-ui.md](docs/chat-ui.md).

## Measure it

`uv run evals` scores any version of each part on its gold cases and compares it with another.
How it works: [src/resourcly/eval_harness/README.md](src/resourcly/eval_harness/README.md). How to
run it, and the current numbers: [docs/evals.md](docs/evals.md).
