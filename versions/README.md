# Versions

Each file here is one named recipe for a component. `versions/<component>/<name>.toml` says which
code to build (`impl`) and gives that code its settings, such as the model or the prompt. A
setting that names a file, such as the router's `probe` or a failure finder's `index`, points to
a file next to the version.
The app and the evals read the same files, so the evals score what the app serves.

## An example

`router/stub-v0.toml`, the smallest version:

```toml
description = "Model-free router for tests and machines without the models: ..."
impl = "stub"
min_paths = 300
```

| Field | Meaning |
| --- | --- |
| `description` | One line for `evals list versions`. Not part of the hash. |
| `impl` | The code to build, a key of `ROUTERS` in `bootstrap.py`. Here `StubRouteAdapter`. |
| `min_paths` | A setting of that code: a PDF whose first page has at least 300 vector paths is a drawing. |

The file name, without `.toml`, is the version's name. Any key other than `description` and
`impl` is a setting, and each `impl` lists the settings it takes and the ones it needs.

## The versions

| Version | What it is | When to use it |
| --- | --- | --- |
| `reader/textlayer-v0` | Title block and notes from the PDF text layer. No model. | For tests and machines without the model; the floor any reader must beat. |
| `reader/whole-page-v1` | Qwen3-VL 8B reads each whole page at 150 dpi, one call per page. | The baseline for the vision readers. |
| `reader/vector-crop-v1` | Each callout found from the PDF's vector paths, with no model; Qwen3-VL 8B reads one crop at a time. | Measured; reads nothing from a page with no vector paths. |
| `reader/vector-crop-v2` | `vector-crop-v1`, and a page with no vector callouts (a scan or an image) read whole as `whole-page-v1` reads it. | The default reader. |
| `router/stub-v0` | A PDF drawn in vector paths is a drawing, an image is a photo. No model. | For tests and machines without the models. |
| `router/three-layer-v1` | Three layers; each decides what it can and passes on the rest. | The default router. |
| | 1. Rules on the file's vector paths, text and pictures. | |
| | 2. A DINOv2-small probe over drawing, photo and other, deciding at 0.9; weights in `router/probes/`. | |
| | 3. Qwen3-VL 8B answers one multiple-choice question. | |
| `failure/shuffled-v0` | Every report figure in one seeded random order. No model. | The floor any failure finder must beat. |
| `failure/dinov2-base-v1` | The report figures nearest the photo in DINOv2-base, none below 0.28; vectors in `failure/indexes/`. | The default failure finder. |
| `failure/dinov2-small-v1` | `dinov2-base-v1` with the router's DINOv2-small. | To compare the two models on the failure gold. |
| `answer/captions-v0` | The closest figures' captions as the answer. No model. | For tests and machines without the model. |
| `answer/photo-v1` | Qwen3-VL 8B answers from the photo and the closest figures, citing each fact. | Its hand check is stored; replaced by v2. |
| `answer/photo-v2` | `photo-v1` asking for the same failure, saying what the photo is, and quoting the report for a stated action ([NOTES.md](../NOTES.md#photo-answers)). | Measured; replaced by v3. |
| `answer/photo-v3` | `photo-v2` naming each figure by its source, with an inferred action shown as a JSON example, not a rule the answer could copy. | The default photo answer. |

The vision readers need `uv sync --extra vlm` and Qwen3-VL 8B in the local Hugging Face cache
(`uv run hf download mlx-community/Qwen3-VL-8B-Instruct-4bit`). `router/three-layer-v1` needs
`uv sync --extra router --extra vlm` and both models in the local Hugging Face cache ([docs/routing.md](../docs/routing.md#run-it)).
`failure/dinov2-base-v1` needs `--extra router` and `facebook/dinov2-base`, and the `answer/photo-*`
versions need Qwen3-VL 8B.

## Which version runs

| Component | Default | Switch with |
| --- | --- | --- |
| reader | `vector-crop-v2` | `RESOURCLY_READER_VERSION` |
| router | `three-layer-v1` | `RESOURCLY_ROUTER_VERSION` |
| failure | `dinov2-base-v1` | `RESOURCLY_FAILURE_VERSION` |
| answer | `photo-v3` | `RESOURCLY_ANSWER_VERSION` |

For example, `RESOURCLY_READER_VERSION=textlayer-v0 RESOURCLY_ROUTER_VERSION=stub-v0
RESOURCLY_FAILURE_VERSION=shuffled-v0 RESOURCLY_ANSWER_VERSION=captions-v0 uv run resourcly serve`
runs without any model. The defaults are in `Settings` in `src/resourcly/bootstrap.py`. A file with an unknown
`impl` or setting, or a missing named file, refuses to load.

## How the app code uses a version

All of it is in `src/resourcly/bootstrap.py`.

1. `Settings.versions` holds the version name of each component: the default, or the
   environment variable.
2. `load_version` reads `versions/<component>/<name>.toml` and checks it against the
   `Implementation` registered for its `impl` in `READERS`, `ROUTERS`, `FINDERS` or `ANSWERERS`.
   It returns a `Version` whose hash covers the settings and any file they name.
3. `Services` builds the component on first use: the `Implementation`'s `build` turns the
   settings into an adapter, such as `StubRouteAdapter(min_paths=300)`.
4. The service writes the version, such as `router stub-v0 (stub)`, into each trace step.

The evals take the same path: `evals run` swaps in the named version with
`Settings.with_version` and calls the same `open_services`.

## How versions fit the workflow

1. Add a version file to try a change. Leave old files alone, so old runs keep their meaning.
2. Score it on the dev split: `uv run evals run router --version my-router-v2`.
3. Compare it with the current one: `uv run evals compare router three-layer-v1 my-router-v2`.
   It compares each version's latest run, so the current one needs a run too.
4. If it is better, make it the default in `Settings`.

## Add a version

```sh
cp versions/router/three-layer-v1.toml versions/router/my-router-v2.toml
uv run evals list versions router
```

Edit the copy. `impl` must be in `READERS`, `ROUTERS`, `FINDERS` or `ANSWERERS` in `bootstrap.py`, and other
keys must be settings it lists. `evals compare` warns about a version edited after its runs. More
in the [eval harness README](../src/resourcly/eval_harness/README.md#add-a-version).
