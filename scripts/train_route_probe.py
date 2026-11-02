"""Train the router's probe on the train split and write its weights as JSON.

    uv run --extra router --group router-build python scripts/train_route_probe.py \\
        --out versions/router/probes/dinov2-small-v1.json

The probe is a logistic regression (scikit-learn, L2, balanced class weights) on the frozen
encoder's embedding of each drawing and photo file in the split's units, with drawing as the
positive class. Messages sent with a file repeat that file, and items that fit no case are not
drawings or photos, so neither is trained on. A version file names the probe file,
so write a new file under a new name rather than overwriting one that a version uses.
"""

import argparse
import json
from pathlib import Path

from resourcly.bootstrap import ENCODERS, Settings, open_services
from resourcly.eval_harness.cases import Case, route_cases
from resourcly.ports import ImageEncoderPort

CLASSES = ("drawing", "photo")


def training_cases(services, split: str) -> list[Case]:
    return [
        case
        for case in route_cases(services, split)
        if case.gold["expected_route"] in CLASSES and not case.gold.get("attachment")
    ]


def train(services, encoder: ImageEncoderPort, split: str, c: float) -> dict:
    from sklearn.linear_model import LogisticRegression

    cases = training_cases(services, split)
    if not cases:
        raise SystemExit(f"no drawing or photo file in the {split} split")
    vectors = []
    for case in cases:
        vectors.append(encoder.encode(services.gold.route_attachment(case.gold["input"]["file"])))
    labels = [int(case.gold["expected_route"] == "drawing") for case in cases]
    regression = LogisticRegression(C=c, class_weight="balanced", max_iter=5000)
    regression.fit(vectors, labels)
    return {
        "encoder_model": encoder.model_id,
        "positive": "drawing",
        "negative": "photo",
        "regression": {"C": c, "class_weight": "balanced"},
        "trained_on": {
            "split": split,
            "cases": {name: sum(1 for k in cases if k.stratum == name) for name in CLASSES},
            "units": sorted({case.gold["unit"] for case in cases}),
        },
        "weights": [round(float(w), 8) for w in regression.coef_[0]],
        "bias": round(float(regression.intercept_[0]), 8),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, required=True, help="The probe JSON file to write.")
    parser.add_argument("--encoder", default="dinov2", choices=sorted(ENCODERS))
    parser.add_argument("--encoder-model", default="facebook/dinov2-small")
    parser.add_argument("--max-side", type=int, default=1024, help="Picture size for the encoder.")
    parser.add_argument("--split", default="train")
    parser.add_argument("--c", type=float, default=100.0, help="Inverse regularisation strength.")
    args = parser.parse_args()
    encoder = ENCODERS[args.encoder](args.encoder_model, args.max_side)
    with open_services(Settings.from_env()) as services:
        document = train(services, encoder, args.split, args.c)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(document, indent=1) + "\n", encoding="utf-8")
    seen = document["trained_on"]["cases"]
    print(f"wrote {args.out}: {seen['drawing']} drawings and {seen['photo']} photos")


if __name__ == "__main__":
    main()
