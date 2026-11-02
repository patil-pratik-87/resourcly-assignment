# Drawing experiments

These notebooks chose how the agent reads a technical drawing into JSON. They are saved with their
outputs. The research behind them: `research/drawing/README.md`.

| Notebook | Question |
| --- | --- |
| `callout_boxes.ipynb` | How are the callouts found from the PDF's vector paths, with no model? |
| `other_options.ipynb` | First tests of OCR, Docling, and Qwen3-VL on a page or a crop. |
| `01_vector_crop_reader.ipynb` | P1, `vector-crop-v1`: Qwen3-VL 8B reads one located crop at a time. |
| `02_whole_page_reader.ipynb` | P2, `whole-page-v1`: it reads each whole page at 150 dpi. |
| `03_compare.ipynb` | Which reader wins, on all gold and on dev? |
| `04_winner_outputs.ipynb` | The winner on all 11 drawings; writes `outputs/`. |

## Result

`vector-crop-v1` wins on all gold and wrote `outputs/`. Numbers from `uv run evals`:

| Reader | Split | F1 | Precision | Recall | Partial recall | Seconds per page |
| --- | --- | --- | --- | --- | --- | --- |
| `textlayer-v0` (floor) | all | 0.344 | 0.902 | 0.213 | 0.129 | 0 |
| `whole-page-v1` | all | 0.650 | 0.629 | 0.672 | 0.543 | 36 |
| `vector-crop-v1` | all | **0.725** | 0.625 | **0.862** | **0.743** | 64 |
| `whole-page-v1` | dev | **0.757** | 0.709 | 0.812 | 0.633 | 33 |
| `vector-crop-v1` | dev | 0.739 | 0.620 | **0.917** | **0.867** | 64 |

- **Why it wins:** one short answer per callout, so dense sheets lose nothing (FTC-06 recall 0.865
  against 0.562), and a 300 dpi crop shows the GD&T symbol, which the whole page often misses.
- **Where it does not:** dev F1 (two full-gold drawings), CTC-03 and FTC-07 page 2. Its extra
  predictions are frame cells read again as bare numbers, a two-line note read as two notes, and
  text of a neighbouring callout cut by the crop edge: fixes for a `vector-crop-v2`, tuned on dev.

Times are on an M1 Pro with 16 GB. No prompt was tuned on the test drawings CTC-03 and FTC-06. The
runs say "local changes": only the notebooks' dependency group was uncommitted.

## Running them again

The model runs take 18 and 32 minutes, so they are made from the command line and the notebooks
read them from the run store (`runs/`):

```sh
uv sync --extra vlm --group experiments
uv run evals run reader --version textlayer-v0 --split all   # and --split dev
uv run --extra vlm evals run reader --version whole-page-v1 --split all
uv run --extra vlm evals run reader --version vector-crop-v1 --split all
(cd experiments/drawing && uv run --extra vlm --group experiments jupyter lab)
```

The readers need `mlx-community/Qwen3-VL-8B-Instruct-4bit` in the local Hugging Face cache and
never download it. `callout_boxes` and `other_options` use their own environment;
`other_options` also needs `rapidocr onnxruntime docling mlx-vlm` and downloads its models:

```sh
python3.12 -m venv experiments/drawing/.venv
experiments/drawing/.venv/bin/pip install pymupdf numpy opencv-python-headless matplotlib jupyter
(cd experiments/drawing && .venv/bin/jupyter lab callout_boxes.ipynb)
```
