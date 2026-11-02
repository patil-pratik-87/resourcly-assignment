# Demo chats

Two requests the chat opens with, so a reviewer can look at a drawing and a photo answer before
any model runs. `uv run resourcly serve` adds each one to the request store when it starts,
unless the store has it already, and marks it as a demo. `serve --no-demo` or
`RESOURCLY_DEMO_CHATS=0` leaves them out.

Each folder is one request in the request store's own layout: `request.json`, the uploaded file in
`files/`, a drawing's JSON in `results/`, and `trace.json`, the request's trace events.

| Request | File | Result |
| --- | --- | --- |
| `28c8fc7699d04c04a74a0229ba7d6ae7` | `nist_ctc_01_asme1_rd.pdf` | 23 values, read by `vector-crop-v2` |
| `2007075b8a10405ea9ced3696d4ff56c` | `pos_18-061_fig05_v1.jpg` | a spar cap fatigue crack, answered by `photo-v3` |

## Where each output comes from

Both outputs are real. They were not written by hand.

- The drawing's JSON is `outputs/nist_ctc_01_asme1_rd.json`, the reader's run on all gold. That
  run was `vector-crop-v1`. `vector-crop-v2` only adds a whole-page read for a page with no vector
  callouts, and every NIST page has them, so on this drawing v2 reads the same.
- The photo is a changed copy of report figure 18-061 fig05 from `evals/gold/failure/images/`. It
  was sent through the chat with `photo-v3`, and every step ran for real: the DINOv2-small probe
  routed it at 0.950, `dinov2-base-v1` found the figures, and Qwen3-VL 8B answered. Its record,
  trace and times are the ones that request stored.

The drawing's record and trace were made by sending it through the agent itself, with the stored
JSON replayed where the reader would have run:

- Routing ran for real with `three-layer-v1`: the structure rules decided the drawing.
- The read would have taken milliseconds, so its time is set to 64 s, the reader's average per
  page on the NIST run (`NOTES.md`).
- The reading's answer issues were not stored with `outputs/`, so the trace counts 0.
