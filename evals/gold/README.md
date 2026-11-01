# Gold labels

The answer keys the reader evals score against. A gold document lists every value printed on a
drawing, the physical feature it belongs to, and what it means, in ASME Y14.5 terms.

Every record is a draft (`"status": "draft"`) until a person reviews it and sets it to `approved`.

## Files

| Path | What it is |
| --- | --- |
| `schema.json` | JSON Schema of one gold document, generated from `src/resourcly/models.py`. |
| `drawings/<drawing>.json` | Full gold: every value on every page, or on the pages `page_coverage` lists. |
| `partial/<drawing>.json` | Partial gold: same shape, about ten values per drawing, scored for recall only. |
| `../splits.toml` | Which drawings are in the dev and test splits. |
| `../../scripts/gold_tools/` | Grid render, bbox overlay, and the writer of `schema.json`. |

Check the gold after any change. It runs the package models, then the rules only gold needs (limits
that agree with `raw`, key order, unique ids, references that resolve), then the splits:

```sh
uv run evals check
```

## Status

| Drawing | Kind | Pages | Features | Values |
| --- | --- | --- | --- | --- |
| CTC-01 | full | 1 | 15 | 23 |
| CTC-03 | full | 1 | 12 | 37 |
| FTC-06 | full | 3 | 20 | 89 |
| FTC-07 | full, page 2 only | 1 of 4 | 6 | 25 |
| CTC-02, CTC-04, CTC-05, FTC-08 to FTC-11 | partial | all | as needed | 10 each |

Each partial gold file covers at least four callout kinds, three tolerance styles, every page with values,
and one note or title-block entry.

## Label screen

The label screen is where a person reviews and extends the gold. It shows each page with a numbered
box per value, and a form beside it to fix a record, move its box, or approve it. A save is
validated by the server and written in place, so the change shows up in `git diff`.

```sh
(cd src/ui && npm ci && npm run build)
uv run resourcly ui   # http://127.0.0.1:8000
```

How to use it: [docs/label-screen.md](../../docs/label-screen.md).

## Conventions the schema cannot show

- **`raw`** is the callout as printed: `⌀` for diameter, ` | ` between frame cells, unicode GD&T
  symbols, and printed signs and trailing zeros kept (`⌀20 +0.05/-0.10`).
- **`value`** is a JSON number, `[lower, upper]` for a limit dimension, or null for text.
- **`limits`** are computed from the printed numbers. A geometric zone has `lower` 0.
- **`bbox`** is `[x0, y0, x1, y1]` in fractions of the page as displayed (the PDFs are stored with
  a 270 degree rotation). It covers the callout text and frame, not leaders.
- **Order** is reading order per page: callouts, then notes, then the title block.
- **Not values:** view labels, the notes heading, sheet numbers and NIST element ids.
- **Units** are stated in the notes of FTC-06 to FTC-11. The CTC sheets print none: CTC-01, 02 and
  04 are inferred as mm from their metric number style, CTC-03 and 05 as inches.

## How the gold was made

Pages were rendered at 200 to 600 dpi and each callout was read from the crops. Callouts are vector
paths on most sheets, so only title blocks and notes come from the text layer. Every box was drawn
back onto its page and corrected where it clipped a frame or took in a leader. CTC-01 and CTC-03
were checked row by row against the NIST answer key.

```sh
uv run python scripts/gold_tools/overlay.py nist_ctc_01_asme1_rd   # gold boxes on each page
uv run python scripts/gold_tools/grid.py nist_ctc_01_asme1_rd --region 0.39 0.09 0.47 0.16 --dpi 400 --step 0.01
```

Renders go to `out/gold_tools/`, which git ignores.
