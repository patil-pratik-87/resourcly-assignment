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
| `bc5ea537eea04684b311e4c4c56b184c` | `pos_18-061_fig05_v1.jpg` | a spar cap fatigue crack, answered by `photo-v2` |

## Where each output comes from

Both outputs are real. They were not written by hand.

- The drawing's JSON is `outputs/nist_ctc_01_asme1_rd.json`, the reader's run on all gold. That
  run was `vector-crop-v1`. `vector-crop-v2` only adds a whole-page read for a page with no vector
  callouts, and every NIST page has them, so on this drawing v2 reads the same.
- The photo is a changed copy of report figure 18-061 fig05 from `evals/gold/failure/images/`.
  Its answer is the `photo-v2` run of the spot check, `evals/photo-answers/runs/photo-v2-spot.jsonl`,
  which a person judged right. The chat server had no answered photo to take instead.

The records and traces were made by sending both files through the agent itself, with the stored
outputs replayed where a model would have run:

- Routing ran for real with `three-layer-v1`: the structure rules decided the drawing, and the
  DINOv2-small probe decided the photo at 0.950. The Qwen3-VL layer was not needed.
- The figure search ran for real with `dinov2-base-v1`, and the answer's citations went through
  the real check. The answer came out the same as the stored one, figure scores included.
- The reader's JSON and the answer model's text were replayed. Their two steps would have taken
  milliseconds, so their times are set to the measured ones: 64 s for the read, the reader's
  average per page on the NIST run (`NOTES.md`), and 37.7 s for the answer, the stored run's 38.3 s
  less the figure search.
- The reading's answer issues were not stored with `outputs/`, so the trace counts 0.
