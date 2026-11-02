# Setup

Resourcly runs on an Apple silicon Mac. Qwen3-VL 8B runs through MLX on the Mac's GPU, and
DINOv2 runs through PyTorch. A Mac with 16 GB of memory and about 15 GB of free disk is enough.

## Set up once

```sh
make setup        # or scripts/setup.sh
```

The script prints each step and an `ok` or `fail` line for it:

1. Checks that this is macOS on Apple silicon.
2. Installs uv in `~/.local/bin` if it is missing.
3. Installs the Python packages with the `vlm` (MLX) and `router` (PyTorch) extras.
4. Downloads the models the app runs, with their progress bars: Qwen3-VL 8B 4-bit (about 6 GB),
   DINOv2-small and DINOv2-base. A model that is already downloaded is skipped.
5. Builds the chat screen with Node.js, which it installs with Homebrew if it is missing.
6. Runs `resourcly doctor`.

`--cli-only` skips the chat screen, so Node.js is not needed. `--no-models` skips the downloads.

Setup is the only step that uses the network. After it, the app runs offline: every model loads
from the local Hugging Face cache and is never downloaded at run time. The router's probe and the
failure finder's figure indexes are committed in `versions/`, so setup only checks them.
`make index` rebuilds the figure indexes.

## Run it

```sh
make run          # sets up if needed, then serves the chat on http://127.0.0.1:8000
make evals-quick  # 10 dev cases of every suite
```

| Target | What it runs |
| --- | --- |
| `serve` | `resourcly serve`; `PORT=8123` picks another port |
| `test` | ruff, pytest and the chat screen's tests |
| `evals`, `evals-test` | every suite with the default version, on the dev or test split |
| `compare COMPONENT= A= B=` | `evals compare` of two runs or versions |
| `outputs` | reads the 11 drawings again and rewrites `outputs/` |
| `index` | rebuilds the figure indexes |
| `chat` | builds the chat screen |

## When something is wrong

```sh
make doctor       # or uv run resourcly doctor
```

The doctor prints one line per check: Python, uv, Node.js, the MLX and PyTorch packages, each
model, each version the app runs and the files it names, and the chat screen. A `fail` or `warn`
line is followed by the command that fixes it. It exits with 1 when a problem stops the app, such
as a missing model; a missing chat screen is only a warning, as the CLI works without it.
