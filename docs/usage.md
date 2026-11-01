# Using the agent

The agent takes one message at a time: text, files (PDFs or images), or both. You never say what
you want. The agent decides the case for each file. A drawing comes back as JSON with every value
on it. A picture or a text question gets a reply that this answer is not available yet.

There are two ways in. The CLI runs the agent inside the command. The HTTP API is what a chat
screen uses. Both store requests in the same place, so either one can look up the other's
requests.

```sh
uv sync
uv run resourcly serve            # the API on http://127.0.0.1:8000, for the curl examples
```

## Chat

```sh
uv run resourcly ask "read this" --file data/drawings/nist_ctc_01_asme1_rd.pdf
uv run resourcly ask "why did the bracket crack?"
```

`ask` waits until every file is handled, prints the result for each one, and exits with 1 if any
file failed.

```sh
curl -F text="read this" -F files=@data/drawings/nist_ctc_01_asme1_rd.pdf \
  http://127.0.0.1:8000/api/requests
```

The API answers `202` at once with the request record and does the work in the background.
Poll `GET /api/requests/<id>` until `status` is `done` or `failed`. Each file is one item. An item
goes from `routing` to `queued`, `reading` and `done` for a drawing, or to `answered` for the
other cases. Any step can end in `failed`, with the reason in `error`.

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
length and hash.

```sh
uv run resourcly requests                 # the latest requests, newest first
uv run resourcly request <id>             # each item, then every step
uv run evals show --request <id>          # the steps only
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
| `GET /api/agent` | The reader and router versions in use, and the upload caps. |

| Variable | Default |
| --- | --- |
| `RESOURCLY_READER_VERSION`, `RESOURCLY_ROUTER_VERSION` | `textlayer-v0`, `stub-v0` |
| `RESOURCLY_UPLOADS_DIR` | `var/uploads` |
| `RESOURCLY_TRACE_DB` | `var/traces.sqlite` |
| `RESOURCLY_MAX_UPLOAD_BYTES`, `RESOURCLY_MAX_FILES` | 50 MB, 50 |
