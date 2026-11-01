# Drawing experiments

`callout_boxes.ipynb` shows, step by step, how every annotation ("callout") on a NIST drawing is
located from the PDF's own vector paths, before any model is involved. It is saved with its
outputs, so it can be read on GitHub without running it.

The results and the recommendation are in `research/drawing/README.md`, with pictures in
`research/drawing/review.html`.

## What the notebook shows

On CTC-01, page 1:

1. The page as a model would see it, and its text layer, which holds only the title block.
2. Every drawing instruction on the page counted by colour. Pure blue `(0, 0, 1)` is every
   annotation and nothing else.
3. The blue paths split into letter shapes (filled, with a 0.06 pt outline) and line segments.
4. Letters within two letter heights of each other joined into groups, one group per annotation.
5. Frame walls added to each group, and groups that overlap and run in the same direction merged.
   This gives the 22 callout boxes on the page.
6. The padded 300 dpi crops that the vision-language models read.

A last section does the same from the rendered image alone, with blue pixels instead of blue
paths, and shows why the PDF route is more precise: leaders tie the pixel blobs together.

Set `PDF` in the first cell to another file in `data/drawings/` to try a different drawing, for
example `nist_ftc_06_asme1_rd.pdf`, where close callouts merge into one box.

## Setup

Python 3.12 with PyMuPDF, NumPy, OpenCV, Matplotlib and Jupyter. No model and no network are
needed.

```sh
python3.12 -m venv experiments/drawing/.venv
experiments/drawing/.venv/bin/pip install pymupdf numpy opencv-python-headless matplotlib jupyter
```

Open it from the repository root:

```sh
(cd experiments/drawing && .venv/bin/jupyter lab callout_boxes.ipynb)
```

The notebook reads the drawings from `../../data/drawings`, so it must run from
`experiments/drawing/`.

## Other reading options

`other_options.ipynb` repeats the first tests of the other ways to read a drawing: what the
PDFs hold (text against vector paths, colours), RapidOCR on crops and pages, Docling on a page,
and Qwen3-VL 8B on a whole page against one callout crop at a time, with the prompts in
`prompts/`. It is saved with its outputs. It needs a few more packages, and downloads Qwen3-VL 8B
(5.8 GB) and the OCR and Docling models on the first run; the model cells run only on Apple
Silicon:

```sh
experiments/drawing/.venv/bin/pip install rapidocr onnxruntime docling mlx-vlm
(cd experiments/drawing && .venv/bin/jupyter lab other_options.ipynb)
```

The wider comparison (Qwen3-VL 4B, MechVL-4B, scoring on 46 checks) is summarised in
`research/drawing/README.md` and `research/drawing/review.html`.
