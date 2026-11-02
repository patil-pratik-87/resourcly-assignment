#!/usr/bin/env bash
# Prepare this Mac to run Resourcly: tools, Python packages, models and the chat screen.
#
# This is the only step that uses the network. Afterwards the app runs offline: the models load
# from the local Hugging Face cache and never download. Running it again skips what is done.
#
#   scripts/setup.sh              everything
#   scripts/setup.sh --cli-only   no chat screen, so no Node.js
#   scripts/setup.sh --no-models  no model downloads
set -euo pipefail

cli_only=0
no_models=0
for arg in "$@"; do
  case "$arg" in
    --cli-only) cli_only=1 ;;
    --no-models) no_models=1 ;;
    -h | --help)
      sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "unknown option $arg; use --cli-only, --no-models or --help" >&2
      exit 2
      ;;
  esac
done

cd "$(dirname "$0")/.."
chat=src/frontend/chat
steps=6
step=0

begin() {
  step=$((step + 1))
  printf '\n[%d/%d] %s\n' "$step" "$steps" "$1"
}
ok() { printf '  ok    %s\n' "$1"; }
skip() { printf '  skip  %s\n' "$1"; }
fail() {
  printf '  fail  %s\n' "$1" >&2
  exit 1
}

begin "Check the machine"
if [[ "$(uname -s)-$(uname -m)" != "Darwin-arm64" ]]; then
  fail "this is $(uname -s) $(uname -m); Qwen3-VL runs through MLX on an Apple silicon Mac only"
fi
ok "macOS on Apple silicon"

begin "Install uv"
# The PATH a new shell gets, to tell at the end whether it can run uv
user_path=$PATH
export PATH="$HOME/.local/bin:$PATH"
if command -v uv >/dev/null; then
  ok "$(uv --version) at $(command -v uv)"
else
  curl -LsSf https://astral.sh/uv/install.sh | sh
  command -v uv >/dev/null || fail "uv did not install; see https://docs.astral.sh/uv/"
  ok "$(uv --version) installed in ~/.local/bin"
fi
uv_dir=$(dirname "$(command -v uv)")

begin "Install the Python packages (MLX for Qwen3-VL, PyTorch for DINOv2)"
uv sync --extra vlm --extra router
ok "Python packages installed in .venv"

begin "Download the models the app runs"
if ((no_models)); then
  skip "--no-models"
else
  models=$(uv run resourcly models)
  for model in $models; do
    if HF_HUB_OFFLINE=1 uv run hf download "$model" --quiet >/dev/null 2>&1; then
      ok "$model already downloaded"
    else
      echo "  downloading $model"
      uv run hf download "$model" >/dev/null || fail "$model did not download"
      ok "$model downloaded"
    fi
  done
fi

begin "Build the chat screen"
if ((cli_only)); then
  skip "--cli-only; resourcly serve will serve the API without the screen"
else
  if ! command -v node >/dev/null; then
    command -v brew >/dev/null || fail "Node.js is missing; install it from https://nodejs.org or run with --cli-only"
    echo "  installing Node.js with Homebrew"
    brew install node
  fi
  ok "Node.js $(node --version)"
  if [[ ! -d $chat/node_modules || $chat/package-lock.json -nt $chat/node_modules/.package-lock.json ]]; then
    npm --prefix "$chat" ci --no-audit --no-fund --loglevel=error
  fi
  npm --prefix "$chat" run build >/dev/null || fail "the chat screen did not build; run npm --prefix $chat run build"
  ok "built in $chat/dist"
fi

begin "Check everything with resourcly doctor"
# With the PATH of a new shell, so it agrees with make doctor run later
PATH=$user_path "$uv_dir/uv" run resourcly doctor ||
  fail "fix the problems above, then run scripts/setup.sh again"
printf '\nReady. Start the app with: make run\n'
if [[ ":$user_path:" != *":$uv_dir:"* ]]; then
  printf '\nuv is not on your PATH. Add this line to ~/.zshrc, then open a new shell:\n'
  printf '  export PATH="%s:$PATH"\n' "$uv_dir"
fi
