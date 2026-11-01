# Versions

A version is one configuration of a component: which implementation it uses and its settings,
such as the model, the prompt or the DPI. The app and the evals read the same files, so the
version the evals measure is the version the app serves.
`open_services(settings)` in `src/resourcly/bootstrap.py` loads them.

| Path | What it is |
| --- | --- |
| `<component>/<name>.toml` | One version, such as `reader/textlayer-v0.toml`. |
| `reader/textlayer-v0.toml` | Values from the PDF text layer, no model. |
| `router/stub-v0.toml` | One structure rule per file type, no model. |
| `failure/shuffled-v0.toml` | Every report figure in one seeded random order, no model. |

Each is the model-free floor of its component, and the version the app runs unless told
otherwise. `RESOURCLY_<COMPONENT>_VERSION`, such as `RESOURCLY_ROUTER_VERSION`, picks another, and
`RESOURCLY_VERSIONS_DIR` points everything at another folder.

## Add a version

Copy an existing version file to a new name and edit it. Leave old files alone, so old runs still
say which settings they used. A version's hash covers its settings, so `evals compare` warns about
a version that was edited after its runs.

```sh
cp versions/reader/textlayer-v0.toml versions/reader/my-reader-v1.toml
uv run evals list versions reader
uv run evals run reader --version my-reader-v1 --split dev
```

The keys a version may set are in [docs/evals.md](../docs/evals.md#adding-a-version).
