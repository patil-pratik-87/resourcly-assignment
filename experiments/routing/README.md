# Routing experiments

Re-run the notebook from the stored results (after the setup below), with no model and no network,
in about a minute:

```sh
experiments/routing/.venv/bin/jupytext --to ipynb experiments/routing/routing.py -o experiments/routing/routing.ipynb
(cd experiments/routing && HF_HUB_OFFLINE=1 .venv/bin/jupyter nbconvert --to notebook --execute --inplace routing.ipynb)
```

These experiments compare ways to decide whether a request is a technical drawing, a photo of a
part or text, or a file that fits none of these (labelled `other` here).
The results and the recommendation are in `research/routing/README.md`.

## Files

| File | What it is |
| --- | --- |
| `../../evals/gold/routes/` | the labelled set, now the router's gold: 244 requests in `routes.jsonl` and 214 files in `items/` (see its `README.md`) |
| `build_dataset.py`, `commons_dl.py`, `commons_find.py` | build the labelled set, download the Commons files, and the search that found them |
| `routing.py`, `routing.ipynb` | the notebook (jupytext source, and with outputs): rules A, probes B, zero-shot C, Docling G, local models D and F, layered router E |
| `routing_common.py` | shared code: items, page images, rule features |
| `run_models.py` | asks one local MLX model the routing question for every file |
| `results/` | every measured number as JSON, and the image embeddings (`emb_*.npz`) |

## Setup

The experiments need their own environment (PyTorch, MLX, Jupyter); MLX runs on Apple silicon only.
These are the versions the results were measured with:

```sh
uv venv --python 3.12 experiments/routing/.venv
uv pip install --python experiments/routing/.venv/bin/python \
  mlx-vlm==0.7.11 pymupdf==2.0 opencv-python-headless==5.0.0.93 pillow==13.0.0 numpy==2.5.4 \
  scikit-learn==1.9.1 psutil==7.2.2 torch==2.15.0 torchvision==0.29.2 open-clip-torch==3.3.0 \
  transformers==5.22.1 pandas==3.1.0 matplotlib==3.11.2 jupyter==1.1.1 nbconvert==7.17.2 \
  ipykernel==7.4.0 jupytext==1.19.6
```

The notebook reuses every file in `results/`; delete one to compute it again. Timings are
measured once and stored, because a rerun on a busy machine measures the load.

## Measure again with the models

Recomputing the embeddings or the `model_*.json` files needs the models. Download them once
into the cache every script uses:

```sh
export HF_HOME=experiments/routing/.cache/hf
for repo in facebook/dinov2-small google/siglip2-base-patch16-224 timm/vit_base_patch32_clip_224.openai \
  docling-project/DocumentFigureClassifier-v2.5 mlx-community/Qwen3-VL-2B-Instruct-4bit \
  mlx-community/Qwen3-VL-4B-Instruct-4bit mlx-community/Qwen3-VL-8B-Instruct-4bit \
  LiquidAI/d1-omni-600M-MLX-8bit LiquidAI/d1-2B-MLX-4bit LiquidAI/d1-3B-MLX-4bit; do
  experiments/routing/.venv/bin/hf download "$repo"
done
experiments/routing/.venv/bin/python experiments/routing/run_models.py qwen3vl_2b qwen3vl_4b qwen3vl_8b d1_omni_600m d1_2b d1_3b
```

The six model runs take about an hour on an M1 Pro. They cover 210 of the 214 files: four were
added afterwards, and `run_models.py --update <name>` fills them in. The Qwen3-VL 4B and 8B runs
used local copies of the mlx-community builds; the 8B copy has the same weights (SHA-256) and
gave the stored answers exactly on six files.
