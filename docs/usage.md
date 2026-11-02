# Using the agent

The agent takes one message at a time: text, files (PDFs or images), or both. You never say what
you want. The agent decides the case for each file. A drawing comes back as JSON with every value
on it. A photo of a part gets what is wrong with it and what to do, from the NTSB reports, with
each fact cited ([photo-answers.md](photo-answers.md)). A text question gets a reply that this
answer is not available yet, and a file that fits no case, such as a whole report, gets a reply
that says so.

There are two ways in. The CLI runs the agent inside the command. The HTTP API is what the chat
screen uses ([chat-ui.md](chat-ui.md)). Both store requests in the same place, so either one can
look up the other's requests.

```sh
uv sync --extra router --extra vlm
uv run hf download facebook/dinov2-small                       # the models, downloaded once
uv run hf download facebook/dinov2-base
uv run hf download mlx-community/Qwen3-VL-8B-Instruct-4bit
uv run resourcly serve            # the chat screen and the API on http://127.0.0.1:8000
```

Drawings are read by `vector-crop-v2`, which runs Qwen3-VL 8B through MLX on Apple silicon, about
a minute per page. It reads each callout it finds in the PDF's vector paths; a page with none, such
as a scan or an image upload, is read whole, and its features say so. It loads the model from the
local Hugging Face cache only. Without the model, a drawing fails with a message that names the
download command. A photo is answered by the same model in about 25 s, after DINOv2-base finds
the closest report figures. To run without models, on any machine, read the text layer, which
finds the title block and notes only, route with the stub, and answer a photo with the closest
figures' captions:

```sh
RESOURCLY_READER_VERSION=textlayer-v0 RESOURCLY_ROUTER_VERSION=stub-v0 \
  RESOURCLY_FAILURE_VERSION=shuffled-v0 RESOURCLY_ANSWER_VERSION=captions-v0 uv run resourcly serve
```

`serve` adds two demo chats from `demo/`, a drawing and a photo answered before by the default
versions, so the chat has something to open before any model runs. `uv run resourcly requests`
marks them `demo`, and `serve --no-demo` or `RESOURCLY_DEMO_CHATS=0` leaves them out.

## Chat

```sh
uv run resourcly ask "read this" --file data/drawings/nist_ctc_01_asme1_rd.pdf
uv run resourcly ask "why did this spar crack?" --file crack.jpg
uv run resourcly ask "why did the bracket crack?"
```

`ask` waits until every file is handled, prints the result for each one, and exits with 1 if any
file failed. For a photo it prints the answer, each finding with its source, each action as
stated in a report page, with the words it quotes, or inferred, and the closest report figures
with their scores.

```sh
curl -F text="read this" -F files=@data/drawings/nist_ctc_01_asme1_rd.pdf \
  http://127.0.0.1:8000/api/requests
```

The API answers `202` at once with the request record and does the work in the background.
Poll `GET /api/requests/<id>` until `status` is `done` or `failed`. Each file is one item, and its
`route` says the case the router picked: `drawing`, `photo`, `text`, or `other` for a file that
fits no case. An item goes from `routing` to `queued`, `reading` and `done` for a drawing, from
`routing` to `queued`, `answering` and `answered` for a photo, or to `answered` for the other
cases. Any step can end in `failed`, with the reason in `error`.

A photo's item carries its `answer`, and `reply` holds the same answer as text:

```json
{
  "not_in_reports": false,
  "kept_out": null,
  "matched": true,
  "answer": "Fatigue cracks grew from the attachment holes of the lower spar cap.",
  "findings": [
    {"statement": "Fatigue origins were at the lower surface near hole LC-1.",
     "citation": {"source": "18-061 p2", "report": "18-061", "page": 2, "figure": null}}
  ],
  "actions": [
    {"action": "Inspect the spar cap at the attachment holes.", "basis": "inferred",
     "citation": null, "quote": null}
  ],
  "figures": [
    {"figure": "18-061/fig05", "report": "18-061", "section": "spar_fatigue_N106ER",
     "failure_mode": "fatigue", "score": 0.78}
  ]
}
```

`not_in_reports` is true when nothing is said about the photo, and `kept_out` says why: `gate`
when no report figure is close enough, `unrelated` when the model sees no part in it. The answer
then says so and has no findings, actions or figures. `matched` is true when the model found
that the closest figures show the same failure as the photo: the same kind of damage on the same
kind of part, or the same intact part for a figure of a part with no defect. A match that cites
nothing the model was shown is given as no match. A `stated` action cites a report page and
`quote` holds the words of that page that say to do it; every other action is `inferred`. A
citation with a `figure` names a report figure, whose image is
`GET /api/reports/<report>/figures/<n>.png`.

## Bulk upload

Send many files in one message. `--file` takes a folder too, and `--out` writes each drawing's
JSON there.

```sh
uv run resourcly ask --file data/drawings --out out/drawings
```

```sh
args=(); for f in data/drawings/*.pdf; do args+=(-F "files=@$f"); done
curl "${args[@]}" http://127.0.0.1:8000/api/requests
curl -OJ "http://127.0.0.1:8000/api/requests/<id>/items/nist_ctc_01_asme1_rd/result?download=true"
```

The API takes at most 50 files per message and 50 MB per file.

## Look up a request

Every step is stored under the request id: what the agent did, what it called, with what, for how
long, and any error. The message text is stored only in the request record. The trace keeps its
length and hash. A photo's steps are `failure.find`, the report figures found, and
`answer.photo`, what the model was shown and what it answered.

```sh
uv run resourcly requests                 # the latest requests, newest first
uv run resourcly request <id>             # each item, then every step; an eval case's steps too
```

```sh
curl "http://127.0.0.1:8000/api/requests?limit=20"
curl http://127.0.0.1:8000/api/requests/<id>
curl http://127.0.0.1:8000/api/requests/<id>/trace
```

## Endpoints and settings

| Endpoint | What it does |
| --- | --- |
| `POST /api/requests` | Send a message: form fields `text` and `files` (repeat for many). |
| `GET /api/requests` | The latest requests; `limit` from 1 to 1000. |
| `GET /api/requests/<id>` | One request and the state of each item. |
| `GET /api/requests/<id>/trace` | Every step the request took. |
| `GET /api/requests/<id>/items/<item>/result` | A drawing's JSON; `download=true` saves it. |
| `GET /api/requests/<id>/items/<item>/pages/<n>.png` | Page `n` of a file as an image, a photo too; `dpi` from 36 to 400. |
| `GET /api/reports/<report>/figures/<n>.png` | Figure `n` of a report, such as `18-061/figures/5.png`; `max_side` from 32 to 2048 pixels, 1024 by default. |
| `GET /api/agent` | The reader, router, failure finder and answer versions in use, and the upload caps. |

| Variable | Default |
| --- | --- |
| `RESOURCLY_READER_VERSION`, `RESOURCLY_ROUTER_VERSION` | `vector-crop-v2`, `three-layer-v1` |
| `RESOURCLY_FAILURE_VERSION`, `RESOURCLY_ANSWER_VERSION` | `dinov2-base-v1`, `photo-v2` |
| `RESOURCLY_UPLOADS_DIR` | `var/uploads` |
| `RESOURCLY_TRACE_DB` | `var/traces.sqlite` |
| `RESOURCLY_MAX_UPLOAD_BYTES`, `RESOURCLY_MAX_FILES` | 50 MB, 50 |
| `RESOURCLY_CHAT_UI_DIST` | `src/frontend/chat/dist` |
| `RESOURCLY_DEMO_CHATS` | on; `0` leaves out the demo chats in `demo/` |
