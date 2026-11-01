# Router gold

The router's gold, made for the routing research in `experiments/routing/`: 244 labelled
requests for the routing question. Is a request a technical drawing, a photo of a part, or
text, or a file that fits none of these?

- `routes.jsonl` has one line per request: its label, the file it sends, its message, where it
  came from and how it was made. The docstring of `experiments/routing/build_dataset.py`
  describes every field.
- `items/` holds the 214 files the requests name, in one folder per label: 116 drawings,
  88 photos and 10 files labelled `other` because no case in the brief covers them.
- `commons.json` records, for each of the 20 Wikimedia Commons files, its source page, author,
  licence, download URL and SHA-256.

| Label | Requests | What they are |
| --- | --- | --- |
| drawing | 116 files, plus 5 messages sent with one | the 11 NIST PDFs, page renders, damaged copies, scanned PDFs, a drawing package, an OCRed scan, 7 Commons drawings |
| photo | 88 files, plus 5 messages sent with one | the 71 photos inside the NTSB reports, 5 of them saved as PDFs, 12 Commons photos |
| text | 20 | questions with no attachment, written by hand |
| other | 10 | the 3 report PDFs, 2 report pages as images, a scanned report page with and without OCR, 2 logos, a physics diagram |

No item was invented. 107 items are real files, 107 were made by code from those real files
with fixed random seeds, and 30 are messages written by hand. The review page
`research/routing/dataset.html` shows every item with how it was made.

## Rebuilding it

The files are committed, so nothing needs rebuilding. To check that the build is reproducible:

```sh
python -I experiments/routing/commons_dl.py
experiments/routing/.venv/bin/python -I experiments/routing/build_dataset.py
git status evals/gold/routes
```

`commons_dl.py` downloads the Commons originals into `experiments/routing/.cache/commons/`
(ignored by git) and checks each hash. `build_dataset.py` then writes `items/` and
`routes.jsonl` again, and with the library versions in `experiments/routing/README.md` it gives
the same bytes. `commons_find.py` is the search that found the Commons candidates.

## Licences

- The NIST drawings come from the NIST MBE PMI validation and conformance test models, and the
  NTSB materials laboratory reports from the NTSB docket. Both are works of the US government.
- The Commons files keep their own licences: 8 are public domain, 6 are CC BY-SA 3.0, 3 are
  CC BY-SA 4.0, 2 are CC BY 2.0 and 1 is CC BY-SA 2.0. `commons.json` names the author and the
  source page of each, and every Commons item's `notes` field gives its licence and page.
- The 7 Commons drawings are re-saved as PNG and the 12 Commons photos are shrunk to 2,048
  pixels, so for the CC BY-SA files these are adapted copies under the same licence.
