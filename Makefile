# Shortcuts for the commands in docs/setup.md. Each target is one or two plain commands.
#
#   make setup          download and build everything (the only online step)
#   make run            set up if needed, then serve the chat on http://127.0.0.1:$(PORT)
#   make evals-quick    a sample of 10 dev cases per component
#   make compare COMPONENT=reader A=vector-crop-v1 B=vector-crop-v2

# uv installs itself in ~/.local/bin, which may not be on the PATH yet
UV := $(shell command -v uv 2>/dev/null || echo $(HOME)/.local/bin/uv)

PORT ?= 8000
# Every suite the evals have
SUITES := reader router failure failure-copy answer answer-copy
CHAT := src/frontend/chat
# The reader whose answers outputs/ holds
OUTPUTS_READER := vector-crop-v1

.PHONY: setup doctor run serve chat test evals evals-quick evals-test compare outputs index

setup:
	scripts/setup.sh

doctor:
	$(UV) run resourcly doctor

run:
	@$(UV) run resourcly doctor >/dev/null 2>&1 && test -f $(CHAT)/dist/index.html || scripts/setup.sh
	$(UV) run resourcly serve --port $(PORT)

serve:
	$(UV) run resourcly serve --port $(PORT)

chat:
	npm --prefix $(CHAT) ci --no-audit --no-fund --loglevel=error
	npm --prefix $(CHAT) run build

test:
	$(UV) run ruff check
	$(UV) run ruff format --check
	$(UV) run pytest
	npm --prefix $(CHAT) test

# Each component's default version on the dev split, then its summary
evals:
	for suite in $(SUITES); do $(UV) run evals run $$suite --split dev || exit 1; done

evals-quick:
	for suite in $(SUITES); do $(UV) run evals run $$suite --limit 10 || exit 1; done

evals-test:
	for suite in $(SUITES); do $(UV) run evals run $$suite --split test || exit 1; done

compare:
	@test -n "$(COMPONENT)" -a -n "$(A)" -a -n "$(B)" || \
		{ echo "usage: make compare COMPONENT=reader A=<run or version> B=<run or version>"; exit 2; }
	$(UV) run evals compare $(COMPONENT) $(A) $(B)

# Read all 11 drawings again and write outputs/<drawing>.json from that run
outputs:
	$(UV) run evals run reader --version $(OUTPUTS_READER) --split all
	$(UV) run python scripts/write_outputs.py --version $(OUTPUTS_READER)

# Cut the reports into figures and embed them again, for the two failure finder versions
index:
	$(UV) run python scripts/build_figure_index.py --encoder-model facebook/dinov2-base \
		--out versions/failure/indexes/dinov2-base-v1.json
	$(UV) run python scripts/build_figure_index.py --encoder-model facebook/dinov2-small \
		--out versions/failure/indexes/dinov2-small-v1.json
