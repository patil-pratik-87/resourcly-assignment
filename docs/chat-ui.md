# Chat screen

The chat screen is the browser side of the agent API. You send a message with text, files, or
both, and watch each file get its case and its result. A second screen lists the requests and
shows what the agent did for each one, step by step.

![A drawing read in the chat, with its JSON open](img/chat-ui/chat-drawing.png)

## Start it

```sh
(cd src/frontend/chat && npm ci && npm run build)
uv run resourcly serve   # http://127.0.0.1:8000
```

`serve` serves the built screen and the API on one port. Without a build it serves the API only
and says how to build. `RESOURCLY_CHAT_UI_DIST` points it at another build. The label screen
stays on `uv run resourcly annotation-ui`.

To work on the screen, run the API and the Vite dev server side by side. Vite reloads the page on
each edit and sends every `/api` call to the API.

```sh
uv run resourcly serve                  # the API on port 8000
(cd src/frontend/chat && npm run dev)   # the screen on http://localhost:5173
```

`RESOURCLY_API=http://127.0.0.1:8123 npm run dev` sends the calls to an API on another port.
Before a commit, run `npm test`, `npm run lint` and `npm run build` in `src/frontend/chat`.

## Chat

Type a message, attach files with the clip or drop them anywhere on the page, and press Enter.
Many files in one message is a bulk upload. Each file gets its own card, and a line over the
cards counts how many are read, answered, in progress or failed.

Each card shows the router's answer: the case, the layer that chose it, how sure it was, and why.
A drawing shows its progress while it is read, then the number of values read, with buttons to
show the JSON in place or to download it. A photo or a text question gets a reply that the answer
is not available yet. A file that fits no case gets a reply that says so.

![A bulk upload of seven files](img/chat-ui/bulk-upload.png)

## Requests

The Requests screen lists the latest requests and their files. Pick a file to see its case, its
reply or its JSON, and the trace of its request beside them. The trace lists every step, what it
called and how long it took. Under each routing step it lists every router layer that was asked:
whether it decided or passed the file on, how sure it was, and why. For a bulk upload the trace
starts on the open file's steps, and Whole request shows them all.

The box over the list finds a request by its id or the start of it, even one too old for the
list. The same trace is in a terminal with `uv run resourcly request <id>`.

![The trace of one file, with the router's verdict](img/chat-ui/request-trace.png)

Both screens ask the API again about once a second while any request is working. Nothing streams
yet.
