# Resourcly case study

A chat agent for technical documents: it decides the case for each file, reads technical drawings
into JSON, and stores what it did for every request.

## Use it

```sh
uv sync --extra router --extra vlm
hf download facebook/dinov2-small
hf download mlx-community/Qwen3-VL-8B-Instruct-4bit
uv run resourcly ask "read this" --file data/drawings/nist_ctc_01_asme1_rd.pdf
```

The router's two models run locally and are downloaded once. On a machine without them, set
`RESOURCLY_ROUTER_VERSION=stub-v0`, a router that needs no model.

How to chat, send many drawings at once, and look up a request, from the CLI or over HTTP:
[docs/usage.md](docs/usage.md).

## Measure it

`uv run evals` scores any version of each part on its gold cases and compares it with another.
How it works: [src/resourcly/eval_harness/README.md](src/resourcly/eval_harness/README.md). How to
run it, and the current numbers: [docs/evals.md](docs/evals.md).
