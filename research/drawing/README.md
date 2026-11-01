# Reading every value off a drawing

**Answer:** find each callout from the PDF's own vector paths, then read one crop at a time with Qwen3-VL 8B.
On these NIST PDFs every annotation is drawn in one pure blue that nothing else uses, so PyMuPDF boxes every callout with no model, in 33 s for all 30 pages.
On the 6 tolerance frames tested, the 8B named the GD&T symbol and the datum letters right every time, at 3 to 7 s per crop.
The whole page sent to the same model is the baseline to beat.
The full results, with pictures, are in [`review.html`](review.html).

## The question

For a technical drawing, the agent returns JSON with every value on it, what it belongs to and what it means.
The drawings are the 11 NIST PMI test models in `data/drawings/`, 30 pages in all, and everything runs locally on a MacBook Pro M1 Pro.
A feature control frame (FCF) is the row of boxes that carries one GD&T rule: a symbol such as position ⌖ or flatness ▱, the tolerance, then the datum letters.

## What the PDFs contain

- Vector only, with no raster images.
- On 29 of the 30 pages the text layer holds only the title block, the header and the general notes. Every dimension, tolerance, FCF and datum label is drawn as glyph outlines: CTC-01 has 32 words of text and 268 blue glyph paths.
- FTC-07 is the exception: its callouts are real text, but its symbol font stores symbols as letters (`v` is the counterbore ⌴, `x` the depth ↧), and its frame symbols are still paths.
- Pure blue `(0, 0, 1)` holds every annotation glyph, leader, frame line and arrowhead, and nothing else. Small XYZ axis markers add a few blue letters.
- The text lies on the faces of an isometric view, so it is rotated and sheared.
- The structure holds nothing useful: empty tag trees, no alternate text, no annotations, no 3D data.

## Options tried

Crops: 8 hand-picked crops from CTC-01, CTC-03 and FTC-06 (6 frames, 2 plain dimensions), scored on 46 checks such as each value, the symbol and the datum letters.
Whole pages: F1 on the numbers of CTC-01 and CTC-03, labelled by hand.

| Option | What it is | Key result | Verdict |
| --- | --- | --- | --- |
| PDF tags and structure | Tag tree, alternate text, layers, metadata | Nothing usable; layers only on FTC-07 | No help at run time |
| Docling | Document converter with layout model and OCR | The drawing becomes one picture; every dimension is lost | Ruled out |
| OCR | PP-OCRv5 through RapidOCR | Digits reliable, even on a whole page in 1 to 2 s; Ø read as 0 about half the time; every GD&T symbol lost | Cross-check only |
| Whole-page VLM | The page at 150 dpi to Qwen3-VL | 4B loops. 8B: numbers F1 1.00 and 0.93, but no symbols; on FTC-06 it read Ø.625 as Ø.825, then looped. 54 to 117 s per page | 8B is the baseline |
| VLM on crops, 4B vs 8B | Located crops, a prompt that names the GD&T symbols | 8B: 42 of 46 checks, 6 of 6 symbols, 5 s per crop. 4B: 40 of 46, 5 of 6, 3 s | 8B recommended |
| MechVL-4B, SFT and RL | Qwen3-VL-4B fine-tuned on mechanical drawings | 35 and 38 of 46, below plain Qwen3-VL 4B. RL invents frames and takes 41 s per crop | Dropped |
| OCR text as a prompt hint | RapidOCR lines added to the prompt | Cost every model 1 to 5 checks on crops | Not used |

A survey found no open model proven on drawings like these.
The best published systems fine-tune a detector and a reader, and released no weights; eDOCr2 (MIT) is the only open GD&T-aware OCR, and is untested here.
Other document converters treat a drawing as one picture, like Docling, and cloud readers break the offline rule.

## Recommendation

1. **Locate.** Keep the pure-blue paths, join letters within two letter heights, add the frame walls, merge overlapping groups. [`callout_boxes.ipynb`](../../experiments/drawing/callout_boxes.ipynb) walks through it.
2. **Read.** Cut a padded colour crop at 300 dpi and send it to Qwen3-VL 8B with the symbol-naming prompt, one call per crop. No deskew: the models read the raw crop as well as a straightened one.
3. **Tie to a feature.** Follow the leader to its end point, and optionally ask what feature a wider crop there shows.
4. **Read the real text.** Notes, title block and FTC-07's callouts come from PyMuPDF, with the symbol-font letters mapped back to symbols.

Why:

- The PDF gives exact positions for free, so no detector has to be trained.
- A small crop shows the symbols at full resolution, and one call per crop keeps the output short, which avoids the loops seen on whole pages.
- It was the only setup that named every symbol right.
- The prompt mattered as much as the model: the 4B went from 0 of 5 symbols to 4 of 5 when the prompt named them.

The baseline sends the whole page to Qwen3-VL 8B with no geometry code; expect most numbers, almost no symbols, and a breakdown on dense sheets.

## Failure modes and open questions

- **Grouping on dense sheets.** On FTC-06 one box covered three stacked callouts, and a tight box can clip the symbol cell. The fix is to find each frame as a closed set of blue lines first.
- **Rare symbols.** No model read the counterbore, depth, the "between" arrow or a circled M on each datum.
- **Other colours.** Blue is this CAD export's habit. Shape alone (filled, hairline outline, under 12 pt) found 6,508 of 6,516 blue letters, so the colour can be picked per document. All-black drawings are untested; scans need an OCR text detector.
- **"Belongs to" is coarse:** a hole, not "hole number 3".
- **Small evidence:** 8 crops and 2 labelled pages.
- **Licence:** PyMuPDF is AGPL-3.0; `pypdfium2` is the permissive alternative.

| Open question | Default chosen |
| --- | --- |
| What runs first | Proposal 1, the crops, measured against Proposal 2, the whole page |
| Runtime | mlx-vlm, which ran every test here |
| A drawing-trained model | MechVL-4B tested and dropped |
| What counts as "every value" | Title block, sheet details and general notes in; axis-marker letters and view labels out |
| Gold set | CTC-01, CTC-03 and FTC-06 in full, plus a ten-value spot check on each other drawing; NIST's definitions spreadsheet seeds the CTC labels |

## Details

[`review.html`](review.html) has the tables and pictures, and [`experiments/drawing/`](../../experiments/drawing/) the notebook.

Model cards used: [Qwen3-VL 8B MLX 4-bit](https://huggingface.co/mlx-community/Qwen3-VL-8B-Instruct-4bit), [Qwen3-VL 4B MLX 4-bit](https://huggingface.co/mlx-community/Qwen3-VL-4B-Instruct-4bit), [MechVL-4B RL](https://huggingface.co/XiaofengAlg/MechVL-4B-RL), [MechVL-4B SFT](https://huggingface.co/XiaofengAlg/MechVL-4B-SFT), [RapidOCR](https://github.com/RapidAI/RapidOCR), [Docling](https://github.com/docling-project/docling).
