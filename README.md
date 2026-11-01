# Resourcly case study

A chat agent for technical documents: it decides the case for each file, reads technical drawings
into JSON, and stores what it did for every request.

## Use it

```sh
uv sync
uv run resourcly ask "read this" --file data/drawings/nist_ctc_01_asme1_rd.pdf
```

How to chat, send many drawings at once, and look up a request, from the CLI or over HTTP:
[docs/usage.md](docs/usage.md).
