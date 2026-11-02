# Routing each request

The router decides which case a request is, without being told: a technical drawing, a photo
of a part, a text question, or `other` for a file that fits no case. It is `three-layer-v1`
(`versions/router/three-layer-v1.toml`). Why this design: [research/routing](../research/routing/README.md).

## The three layers

Each layer either decides or passes the request on with its reason. The first to decide wins.

| Layer | Code | What it decides |
| --- | --- | --- |
| `structure` | `adapters/route_structure.py` | No file is text. A PDF of CAD sheets (300+ vector paths, little picture) is a drawing; a prose PDF or an unreadable file is `other`. Images and scans pass on. |
| `probe` | `adapters/route_probe.py`, `adapters/dinov2_encoder.py` | A three-class logistic regression (drawing, photo, other) on the DINOv2-small embedding of the picture (an image, or page 1 of a PDF). Decides when one class reaches 0.9. |
| `vlm` | `adapters/route_vlm.py`, `adapters/mlx_vlm_model.py` | Qwen3-VL 8B answers one multiple-choice question (drawing, photo, something else) about the picture. It never sees the user's text. |

A picture is turned upright from its EXIF orientation before a model sees it. A file that opens
but will not decode or render, such as a truncated JPEG, goes to `other` with the reason instead
of failing the request. Every layer asked is traced as `route.<layer>` with its verdict,
confidence and reason. Both
models load from the local Hugging Face cache with `HF_HUB_OFFLINE=1` and never download.

## Results

| Split | Accuracy | Drawing recall | Other kept out |
| --- | --- | --- | --- |
| dev, 123 requests | 0.992 | 1.000 | 0.833 |
| test, 57 requests | 1.000 | 1.000 | 1.000 |

The one miss is a dimensioned physics diagram that the probe calls a drawing. The model-free
`stub-v0` scores 0.602 accuracy and 0.120 drawing recall on dev.

These near-perfect scores mean the route set is easy, not that the router is perfect. Its phone photos
and scans of drawings are made by code from clean renders. It has no real phone photos of
drawings, no real scanned reports and no mixed pages, such as a drawing beside a photo.

## Run it

```sh
uv sync --extra router --extra vlm
hf download facebook/dinov2-small
hf download mlx-community/Qwen3-VL-8B-Instruct-4bit
uv run evals run router --version three-layer-v1 --split dev
RESOURCLY_ROUTER_VERSION=three-layer-v1 uv run resourcly serve
```

The app runs `stub-v0` by default, so it needs neither model.

## Retrain the probe

The probe's weights are `versions/router/probes/dinov2-small-v1.json`, trained on the router
train split only: 37 drawings, 23 photos and 2 files that fit no case. The version hash covers the file, so a retrained probe goes in a new file and
a new version:

```sh
uv run --extra router --group router-build python scripts/train_route_probe.py \
    --out versions/router/probes/dinov2-small-v2.json
```

## Limits

- The probe saw 62 files, only 2 of them `other`. It must be retrained on the customer's own drawings before these
  numbers apply.
- The dev and test NIST drawings are from the same family as the train ones.
- Bulk upload routes each file in turn; there is no batched routing yet.
