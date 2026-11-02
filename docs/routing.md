# Routing each request

The router decides which case a request is, without being told: a technical drawing, a photo
of a part, a text question, or `other` for a file that fits no case. It is `three-layer-v1`
(`versions/router/three-layer-v1.toml`), the app's default. Why this design:
[research/routing](../research/routing/README.md).

## The three layers

Each layer decides or passes the request on with its reason. The first to decide wins.

| Layer | Code | What it decides |
| --- | --- | --- |
| `structure` | `adapters/route_structure.py` | No file is text. A PDF of CAD sheets is a drawing; a prose PDF or unreadable file is `other`. Images and scans pass on. |
| `probe` | `adapters/route_probe.py`, `adapters/dinov2_encoder.py` | Logistic regression over drawing, photo and other on the DINOv2-small embedding of the picture. Decides when one class reaches 0.9. |
| `vlm` | `adapters/route_vlm.py`, `adapters/mlx_vlm_model.py` | Qwen3-VL 8B answers one multiple-choice question about the picture, never the user's text. |

A picture is turned upright from its EXIF orientation before a model sees it. A file that will
not decode or render, such as a truncated JPEG, goes to `other` with the reason. Each layer
asked is traced as `route.<layer>`. Both models load from the local Hugging Face cache and never
download.

## Results

| Split | Accuracy | Drawing recall | Other kept out |
| --- | --- | --- | --- |
| dev, 123 requests | 0.992 | 1.000 | 0.833 |
| test, 57 requests | 1.000 | 1.000 | 1.000 |

Accuracy counts every request, `other` files too. The one miss is a dimensioned physics diagram
the probe calls a drawing at 0.989. The probe's `other` class decides 3 dev report pages itself,
so 18 dev requests reach Qwen3-VL instead of 23. The model-free `stub-v0` scores 0.602 accuracy
and 0.120 drawing recall on dev.

These near-perfect scores mean the route set is easy, not that the router is perfect. Its phone
photos and scans are made by code from clean renders. It has no real phone photos of drawings,
no real scanned reports and no mixed pages.

## Run it

```sh
uv sync --extra router --extra vlm
hf download facebook/dinov2-small
hf download mlx-community/Qwen3-VL-8B-Instruct-4bit
uv run evals run router --version three-layer-v1 --split dev
uv run resourcly serve
```

`RESOURCLY_ROUTER_VERSION=stub-v0` runs a router that needs neither model.

## Retrain the probe

The weights are `versions/router/probes/dinov2-small-v1.json`, trained on the train split only:
37 drawings, 23 photos and 2 `other` files. The version hash covers the file, so a retrained
probe goes in a new file and a new version:

```sh
uv run --extra router --group router-build python scripts/train_route_probe.py \
    --out versions/router/probes/dinov2-small-v2.json
```

## Limits

- The probe saw 62 files, only 2 of them `other`. It needs the customer's own files.
- The NIST drawings in every split come from one family.
- Bulk upload routes each file in turn.
