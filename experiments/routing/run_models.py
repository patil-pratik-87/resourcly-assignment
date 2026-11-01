"""Ask local MLX models the routing question for every attachment; write results/model_<name>.json.

    experiments/routing/.venv/bin/python experiments/routing/run_models.py qwen3vl_2b d1_2b
    experiments/routing/.venv/bin/python experiments/routing/run_models.py --update qwen3vl_8b

Each model runs in its own process when the notebook calls this script, so its peak memory is
measured alone. Approach D uses Qwen3-VL, a general vision-language model; the option
probabilities come from the logits of the first answer token. Approach F uses LiquidAI's d1
decision models through mlx-vlm's typed decision API, which returns a probability per option by
design. --update keeps the answers already in the result file and asks only about new files.

The models load from the Hugging Face cache in experiments/routing/.cache/hf with the network
off, so download them there once first (see README.md).
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.environ.setdefault("HF_HOME", str(HERE / ".cache" / "hf"))
os.environ["HF_HUB_OFFLINE"] = "1"

import mlx.core as mx  # noqa: E402
import numpy as np  # noqa: E402
import routing_common as common  # noqa: E402

# name: (kind, Hugging Face repo)
MODELS = {
    "qwen3vl_2b": ("qwen", "mlx-community/Qwen3-VL-2B-Instruct-4bit"),
    "qwen3vl_4b": ("qwen", "mlx-community/Qwen3-VL-4B-Instruct-4bit"),
    "qwen3vl_8b": ("qwen", "mlx-community/Qwen3-VL-8B-Instruct-4bit"),
    "d1_omni_600m": ("d1", "LiquidAI/d1-omni-600M-MLX-8bit"),
    "d1_2b": ("d1", "LiquidAI/d1-2B-MLX-4bit"),
    "d1_2b_8bit": ("d1", "LiquidAI/d1-2B-MLX-8bit"),
    "d1_3b": ("d1", "LiquidAI/d1-3B-MLX-4bit"),
}
MAX_SIDE = 768
OPTIONS = ("drawing", "photo", "other")
QWEN_QUESTION = (
    "Which one best describes this image?\n"
    "A) a technical or engineering drawing (a CAD drawing sheet or dimensioned diagram, "
    "or a photo or scan of one)\n"
    "B) a photograph of a physical part, material, fracture surface or micrograph\n"
    "C) something else, such as a page of text, a logo or a chart\n"
    "Answer with the letter only."
)
D1_QUESTION = {
    "case": {
        "type": "choice",
        "instructions": "What kind of image is this?",
        "criteria": {
            "drawing": (
                "a technical or engineering drawing, CAD sheet or dimensioned diagram, "
                "or a photo or scan of one"
            ),
            "photo": "a photograph of a physical part, material, fracture surface or micrograph",
            "other": "anything else, such as a page of text, a logo or a chart",
        },
    }
}


def input_image(item: dict) -> str:
    """The attachment as a PNG of at most MAX_SIDE pixels, shared by every model."""
    out = common.CACHE / "vlm_in" / f"{item['id']}.png"
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        common.attachment_image(item, MAX_SIDE).save(out)
    return str(out)


def qwen_runner(repo: str):
    """ask(image, text) -> ({option: probability}, extras) for a Qwen3-VL model."""
    from mlx_vlm import load, stream_generate
    from mlx_vlm.prompt_utils import apply_chat_template

    model, processor = load(repo)
    tokenizer = processor.tokenizer
    letter_ids = [tokenizer.encode(letter, add_special_tokens=False)[0] for letter in "ABC"]

    def ask(image: str, text: str | None):
        question = QWEN_QUESTION
        if text:
            question = f'The user sent this image with the message: "{text}"\n\n{QWEN_QUESTION}'
        prompt = apply_chat_template(processor, model.config, question, num_images=1)
        for step in stream_generate(
            model, processor, prompt, image=[image], max_tokens=1, temperature=0.0
        ):
            logprobs = np.array(step.logprobs.astype(mx.float32)).reshape(-1)
            letters = logprobs[letter_ids]
            probs = np.exp(letters - letters.max())
            probs /= probs.sum()
            return dict(zip(OPTIONS, probs.tolist(), strict=True)), {
                "prompt_tokens": step.prompt_tokens,
                # how much of the first token's probability the three letters hold
                "letter_mass": float(np.exp(letters).sum()),
                "raw": step.text,
            }
        raise RuntimeError("no token generated")

    return ask


def d1_runner(repo: str):
    """ask(image, text) -> ({option: probability}, extras) for a LiquidAI d1 decision model."""
    from mlx_vlm.decision import predict
    from mlx_vlm.utils import load

    model, processor = load(repo)
    # The LFM3-based d1 models (d1-2B) answer through system_one; the others through predict.
    system_one = callable(getattr(model, "system_one", None))

    def ask(image: str, text: str | None):
        state = f"User message: {text}" if text else None
        if system_one:
            reply = model.system_one(state, D1_QUESTION, [{"type": "image", "path": image}])
            answer = reply["answers"]["case"]
            confidence = answer.get("confidence")
        else:
            reply = predict(model, processor, state, D1_QUESTION, images=[image])
            answer = reply["answers"]["case"]
            confidence = answer.get("metadata", {}).get("confidence")
        probs = {option: float(answer["probabilities"][option]) for option in OPTIONS}
        return probs, {"confidence": confidence, "usage": reply.get("usage")}

    return ask


def answer_record(ask, image: str, text: str | None) -> dict:
    start = time.perf_counter()
    probs, extras = ask(image, text)
    ms = (time.perf_counter() - start) * 1000
    return {"p": probs, "pred": max(probs, key=probs.get), "ms": ms, **extras}


def main(name: str, update: bool = False) -> None:
    """Run one model over every attachment and every message with an attachment."""
    kind, repo = MODELS[name]
    items = common.load_items()
    by_id = {it["id"]: it for it in items}
    attachments = [it for it in items if it.get("file") and it["variant"] != "text_pair"]
    pairs = [it for it in items if it["variant"] == "text_pair"]
    images = {it["id"]: input_image(it) for it in attachments}
    previous = common.load_json(f"model_{name}.json") if update else None

    rss_before = common.rss_mb()
    start = time.perf_counter()
    ask = (qwen_runner if kind == "qwen" else d1_runner)(repo)
    load_s = time.perf_counter() - start
    ask(images[attachments[0]["id"]], None)  # warm-up, not timed

    out = {
        "model": name,
        "repo": repo,
        "kind": kind,
        "max_side": MAX_SIDE,
        "items": {},
        "pairs": {},
    }
    if previous:
        out["items"] = {k: v for k, v in previous["items"].items() if k in images}
        out["pairs"] = {k: v for k, v in previous["pairs"].items() if k in by_id}
        attachments = [it for it in attachments if it["id"] not in out["items"]]
        pairs = [it for it in pairs if it["id"] not in out["pairs"]]
        load_s = previous["stats"]["load_s"]
        print(f"{name}: updating {len(attachments)} items and {len(pairs)} pairs", flush=True)
    for k, it in enumerate(attachments):
        record = answer_record(ask, images[it["id"]], None)
        out["items"][it["id"]] = record
        if k % 25 == 0:
            print(
                f"{name} {k}/{len(attachments)} {it['id']} -> {record['pred']} "
                f"{record['ms']:.0f} ms",
                flush=True,
            )
    for it in pairs:
        out["pairs"][it["id"]] = answer_record(ask, images[it["attachment"]], it["text"])

    ms = [record["ms"] for record in out["items"].values()]
    peak_gb = mx.get_peak_memory() / 1e9
    out["stats"] = {
        "load_s": load_s,
        "ms_median": float(np.median(ms)),
        "ms_p95": float(np.percentile(ms, 95)),
        "peak_mlx_gb": max(peak_gb, previous["stats"]["peak_mlx_gb"]) if previous else peak_gb,
        "rss_delta_mb": previous["stats"]["rss_delta_mb"]
        if previous
        else common.rss_mb() - rss_before,
    }
    common.save_json(f"model_{name}.json", out)
    print(name, json.dumps(out["stats"]))


if __name__ == "__main__":
    args = sys.argv[1:]
    for model_name in (a for a in args if a != "--update"):
        main(model_name, update="--update" in args)
