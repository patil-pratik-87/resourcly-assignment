# ---
# jupyter:
#   jupytext:
#     formats: ipynb,py:percent
#   kernelspec:
#     display_name: Python 3
#     language: python
#     name: python3
# ---

# %% [markdown]
# # Routing experiments: drawing, part photo or text
#
# The agent must decide, without being told, whether a request is a technical drawing (return
# every value as JSON), a photo of a part (say what is wrong) or text only. This notebook
# measures several ways to make that decision on a labelled set of 244 items, on an M1 Pro with
# 16 GB and no network (`HF_HUB_OFFLINE=1`).
#
# - **A** deterministic rules: PDF structure, camera EXIF, pixel statistics
# - **B** a linear probe (logistic regression) on a frozen image embedding: CLIP, SigLIP 2, DINOv2
# - **C** zero-shot CLIP and SigLIP 2 with text prompts, no training
# - **D** a local vision-language model asked one routing question (Qwen3-VL 2B, 4B, 8B)
# - **F** local open-weight decision models that answer a typed choice with probabilities
#   (LiquidAI d1 family through mlx-vlm)
# - **G** a pretrained document-figure classifier (Docling DocumentFigureClassifier v2.5)
# - **E** the layered router: A, then B when A is undecided, then D or F when B is unsure
#
# The letters are the order the options were written down in, not a ranking. Every measured
# result is cached under `results/`, so the notebook re-runs in about a minute without loading
# any vision-language model; delete a file there to recompute it.

# %%
import gc
import itertools
import json
import os
import subprocess
import sys
import time
import warnings
from collections import Counter
from pathlib import Path

HERE = Path.cwd()  # the notebook runs in its own folder
if not (HERE / "routing_common.py").exists():  # run as a script from elsewhere
    HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.environ["HF_HOME"] = str(HERE / ".cache" / "hf")
os.environ["HF_HUB_OFFLINE"] = "1"  # prove every model runs without the network
os.environ["TOKENIZERS_PARALLELISM"] = "false"

import numpy as np
import pandas as pd
import pymupdf
import routing_common as common
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss
from sklearn.model_selection import LeaveOneGroupOut, StratifiedGroupKFold, StratifiedKFold

try:
    display  # noqa: B018
except NameError:  # running as a plain script
    display = print

warnings.filterwarnings("ignore")
pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 30)
pd.set_option("display.max_colwidth", 80)

ITEMS = common.load_items()
BY_ID = {it["id"]: it for it in ITEMS}
# Items with their own attachment (a message with an attachment reuses another item's file).
ATTACH = [it for it in ITEMS if it.get("file") and it["variant"] != "text_pair"]
MAIN = [it for it in ATTACH if it["label"] in ("drawing", "photo")]
EDGE = [it for it in ATTACH if it["label"] == "other"]  # files that fit no case
PAIRS = [it for it in ITEMS if it["variant"] == "text_pair"]
TEXT = [it for it in ITEMS if it["kind"] == "text"]
print(len(ITEMS), "items:", dict(Counter(it["label"] for it in ITEMS)))
print(
    f"attachments to classify: {len(MAIN)} drawings and photos + {len(EDGE)} that fit no case; "
    f"{len(PAIRS)} messages with an attachment; {len(TEXT)} text only"
)
pd.crosstab([it["label"] for it in ITEMS], [it["variant"] for it in ITEMS])

# %% [markdown]
# ## Splits
#
# Degraded variants of one page are near duplicates, so a random split leaks: the same sheet
# lands on both sides. Every honest split below groups by **source**: one NIST drawing (all its
# pages and variants), one NTSB report, or one Commons file. This is the item's `unit`.
#
# Grouping by report page instead is not enough: photos of one specimen on neighbouring pages of
# a report then sit on both sides of a fold, which makes the probes look surer than they are.
# The page grouping is kept only to show, in section E, how much the escalation rate depends on
# the grouping.

# %%
main_ids = [it["id"] for it in MAIN]
y_main = np.array([1 if it["label"] == "drawing" else 0 for it in MAIN])  # 1 = drawing
groups = np.array([it["unit"] for it in MAIN])
groups_page = np.array([it["group"] for it in MAIN])  # the finer grouping, by report page
print(len(set(groups)), "source groups,", len(set(groups_page)), "page groups")
HALF = list(  # two grouped halves
    StratifiedGroupKFold(n_splits=2, shuffle=True, random_state=7).split(
        np.zeros(len(MAIN)), y_main, groups
    )
)
RANDOM_HALF = list(  # two random halves, which leak; for comparison only
    StratifiedKFold(n_splits=2, shuffle=True, random_state=7).split(np.zeros(len(MAIN)), y_main)
)
for half, (train, test) in enumerate(HALF):
    print(
        f"grouped half {half}: train {len(train)} ({y_main[train].sum()} drawings), "
        f"test {len(test)} ({y_main[test].sum()} drawings)"
    )


def label_of(p_drawing, threshold=0.5):
    return "drawing" if p_drawing >= threshold else "photo"


def accuracy(y_true, y_pred):
    y_true, y_pred = list(y_true), list(y_pred)
    return sum(a == b for a, b in zip(y_true, y_pred, strict=True)) / len(y_true)


# %% [markdown]
# ## A. Deterministic rules
#
# One pass computes every signal (about 40 ms per item, all CPU):
#
# - **PDF**: for each of the first ten pages, the number of vector paths, the characters of real
#   text and the share of the page covered by pictures. A page 1 with 300 or more vector paths
#   and almost no picture is a drawing. Otherwise the rule counts the first ten pages: a CAD sheet
#   has 300 or more paths and little picture, and a page of prose has 1,000 or more characters
#   and is not one big picture. A PDF with at least as many CAD sheets as prose pages is a drawing
#   package; one with more prose pages is a document (the NTSB reports), which no case in the
#   brief covers. A page 1 that is one big picture is judged by the image rules below, so the text
#   layer of an OCRed scan never decides. An earlier version of the prose rule used "1,500
#   characters on page 1, or 1,000 on any of the first ten pages", which binned a drawing package
#   with a notes sheet and an OCRed scan of a report as documents. That earlier rule was itself
#   added after the 24-013 report (a cover page with 200 characters) reached the probe, so the
#   prose part of layer 1 has been fitted to this set twice.
# - **Image**: camera EXIF (Make or Model tag), the share of near-white pixels, and the share of
#   "flat" pixels whose Laplacian is near zero (paper and solid fills are flat, photographs are
#   textured). Saturation, colour concentration and straight-edge ratio are computed too; they
#   did not separate the classes better than these two (see the medians below).
#
# Rules must be high precision: they decide only when sure and say "undecided" otherwise.
# The four cut points are fitted on grouped half 0 by grid search: among settings with no error
# on that half, take the one that decides the most items. It is then scored on half 1.

# %%
# The features are computed and timed once and cached, because a rerun on a busy machine
# measures the load; delete rule_features.json to compute and time them again.
FEATS = common.load_json("rule_features.json")
if FEATS is None:
    FEATS = {}
    for it in ATTACH:
        with common.Timer() as timer:
            FEATS[it["id"]] = common.rule_features(it)
        FEATS[it["id"]]["ms"] = timer.ms
    for it in TEXT:
        FEATS[it["id"]] = {"kind": "text", "ms": 0.0}
    common.save_json("rule_features.json", FEATS)
for it in PAIRS:  # a message with an attachment has its file's features
    FEATS[it["id"]] = FEATS[it["attachment"]]

features_df = pd.DataFrame(
    [
        {"id": it["id"], "label": it["label"], "variant": it["variant"], **FEATS[it["id"]]}
        for it in ATTACH
    ]
)
print(
    f"rule feature time per attachment: median {features_df.ms.median():.0f} ms, "
    f"max {features_df.ms.max():.0f} ms"
)
features_df.groupby(["label", "variant"])[
    [
        "white_frac",
        "flat_frac",
        "sat_mean",
        "top8_share",
        "straight_ratio",
        "pdf_vector_paths",
        "pdf_chars",
    ]
].median().round(2)


# %%
def rule_decisions(ids, thresholds):
    return [common.decide_rules(FEATS[i], thresholds)[0] for i in ids]


def fit_rules(train_ids, use_exif):
    """The cut points with no wrong decision on train_ids that decide the most of them."""
    truth = [BY_ID[i]["label"] for i in train_ids]
    best_key, best = None, None
    grid = itertools.product(
        [0.3, 0.4, 0.5, 0.6, 0.7],  # drawing_white
        [0.5, 0.6, 0.65, 0.7, 0.75, 0.8],  # drawing_flat
        [0.02, 0.05, 0.1, 0.15, 0.2, 0.3],  # photo_white
        [0.2, 0.3, 0.4, 0.5, 0.6, 0.7],  # photo_flat
    )
    for drawing_white, drawing_flat, photo_white, photo_flat in grid:
        thresholds = common.RuleThresholds(
            use_exif=use_exif,
            drawing_white=drawing_white,
            drawing_flat=drawing_flat,
            photo_white=photo_white,
            photo_flat=photo_flat,
        )
        decided = rule_decisions(train_ids, thresholds)
        pairs = list(zip(decided, truth, strict=True))
        wrong = sum(d in ("drawing", "photo") and d != y for d, y in pairs)
        covered = sum(d in ("drawing", "photo") for d in decided)
        key = (-wrong, covered)
        if best_key is None or key > best_key:
            best_key, best = key, thresholds
    return best


def score_rules(ids, thresholds):
    truth = [BY_ID[i]["label"] for i in ids]
    decisions = rule_decisions(ids, thresholds)
    decided = [(d, y) for d, y in zip(decisions, truth, strict=True) if d != "undecided"]
    return {
        "items": len(ids),
        "coverage": len(decided) / len(ids),
        "precision_when_decided": accuracy([y for _, y in decided], [d for d, _ in decided])
        if decided
        else None,
        "accuracy_undecided_counts_wrong": accuracy(truth, decisions),
    }


RULE_FITS = {}
train_ids = [main_ids[i] for i in HALF[0][0]]
test_ids = [main_ids[i] for i in HALF[0][1]]
for use_exif in (True, False):
    thresholds = fit_rules(train_ids, use_exif)
    RULE_FITS[f"exif={use_exif}"] = {
        "thresholds": thresholds.__dict__,
        "train_half": score_rules(train_ids, thresholds),
        "test_half": score_rules(test_ids, thresholds),
        "all_main": score_rules(main_ids, thresholds),
    }
RULES_EXIF = common.RuleThresholds(**RULE_FITS["exif=True"]["thresholds"])
RULES_NO_EXIF = common.RuleThresholds(**RULE_FITS["exif=False"]["thresholds"])
pd.DataFrame(
    {
        name: {
            **fit["thresholds"],
            **{f"test {k}": v for k, v in fit["test_half"].items()},
            **{f"all {k}": v for k, v in fit["all_main"].items()},
        }
        for name, fit in RULE_FITS.items()
    }
)


# %%
def rules_table(thresholds):
    """Every item with the rules' decision and its reason."""
    rows = []
    for it in ITEMS:
        decision, why = common.decide_rules(FEATS[it["id"]], thresholds)
        rows.append(
            {
                "id": it["id"],
                "label": it["label"],
                "variant": it["variant"],
                "decision": decision,
                "why": why,
            }
        )
    return pd.DataFrame(rows)


rules_exif = rules_table(RULES_EXIF)
print("Approach A with EXIF, all items (text included):")
display(pd.crosstab(rules_exif.label, rules_exif.decision, margins=True))
print("Where A decided wrongly:")
display(
    rules_exif[
        rules_exif.decision.isin(["drawing", "photo", "text"])
        & (rules_exif.decision != rules_exif.label)
        & (rules_exif.label != "other")
    ]
)
print("What A left undecided, by variant:")
display(
    rules_exif[rules_exif.decision == "undecided"]
    .groupby(["label", "variant"])
    .size()
    .rename("undecided")
)
rules_no_exif = rules_table(RULES_NO_EXIF)
print("Without the EXIF rule:")
display(pd.crosstab(rules_no_exif.label, rules_no_exif.decision, margins=True))

# %% [markdown]
# **Structure-only rules.** Every wrong decision above is a drawing photographed on a desk: its
# pixels look like a photo, and 8 of the 15 phone copies carry phone EXIF. So the variant used
# as layer 1 of the layered router keeps only the signals that come from the file's structure:
# no attachment means text, a vector PDF or drawing package means drawing, a prose PDF means
# document. Every raster image, and every PDF that is one big picture, goes on to layer 2.

# %%
# Image cut points that can never be met, so only the PDF and text rules decide.
RULES_STRUCTURE = common.RuleThresholds(
    use_exif=False, drawing_white=2.0, drawing_flat=2.0, photo_white=-1.0, photo_flat=-1.0
)
pdf_items = [it for it in ATTACH if it["kind"] == "pdf"]
saved_rules = common.load_json("A_rules.json") or {}

# The structure check at scale: PyMuPDF's get_cdrawings() returns the same paths as
# get_drawings() as plain tuples, which its documentation says is much faster.
# Like every timing here, it is measured once and cached; delete A_rules.json to time it again.
STRUCT_MS = saved_rules.get("struct_check_ms")
if STRUCT_MS is None:
    page1_ms = {"get_drawings": [], "get_cdrawings": []}
    for it in pdf_items:
        for method in page1_ms:
            start = time.perf_counter()
            with pymupdf.open(common.item_path(it)) as doc:
                page = doc[0]
                getattr(page, method)()
                page.get_text()
                page.get_images(full=True)
            page1_ms[method].append((time.perf_counter() - start) * 1000)
    STRUCT_MS = {
        method: {"median": float(np.median(ms)), "max": float(np.max(ms))}
        for method, ms in page1_ms.items()
    }
print("page 1 structure check per PDF, ms:", STRUCT_MS)


def layer1_check(path):
    """The layer-1 check as a router would run it: page 1 first, and pages 2 to 10 only when
    page 1 is not a CAD sheet."""
    with pymupdf.open(path) as doc:
        paths, _, cover = common.page_layout(doc[0])
        if paths >= RULES_STRUCTURE.pdf_vector_paths and cover < 0.2:
            return
        for i in range(1, min(10, doc.page_count)):
            common.page_layout(doc[i])


# Timed per PDF as the median of three runs, and cached; section E uses these times.
STRUCT10_MS = saved_rules.get("struct_check_layer1_ms", {})
for it in pdf_items:
    if it["id"] not in STRUCT10_MS:
        runs = []
        for _ in range(3):
            start = time.perf_counter()
            layer1_check(common.item_path(it))
            runs.append((time.perf_counter() - start) * 1000)
        STRUCT10_MS[it["id"]] = float(np.median(runs))
print(
    f"layer-1 check per PDF: median {np.median(list(STRUCT10_MS.values())):.1f} ms, "
    f"max {max(STRUCT10_MS.values()):.1f} ms"
)
display(
    pd.DataFrame(
        {"ms": [STRUCT10_MS[it["id"]] for it in pdf_items]},
        index=[it["variant"] for it in pdf_items],
    )
    .groupby(level=0)
    .median()
    .round(1)
)
rules_structure = rules_table(RULES_STRUCTURE)


def earlier_prose_rule(f):
    """The earlier prose rule, kept only to show what counting page kinds changed."""
    if f["pdf_vector_paths"] >= 300 and f["pdf_image_cover"] < 0.2:
        return "drawing"
    if f["pdf_chars"] >= 1500 and f["pdf_vector_paths"] < 300:
        return "document"
    if f["pdf_image_cover"] < 0.5 and f["pdf_max_chars_first10"] >= 1000:
        return "document"
    return "undecided"


now = dict(zip(rules_structure.id, rules_structure.decision, strict=True))
pdf_calls = pd.DataFrame(
    [
        {
            "id": it["id"],
            "label": it["label"],
            "earlier rule": earlier_prose_rule(FEATS[it["id"]]),
            "now": now[it["id"]],
        }
        for it in pdf_items
    ]
)
print("PDFs whose layer-1 call changed when the rule started counting page kinds:")
display(pdf_calls[pdf_calls["earlier rule"] != pdf_calls["now"]])
display(pd.crosstab(rules_structure.label, rules_structure.decision, margins=True))
common.save_json(
    "A_rules.json",
    {
        "fits": RULE_FITS,
        "decisions": rules_exif.to_dict("records"),
        "decisions_noexif": rules_no_exif.to_dict("records"),
        "decisions_structural": rules_structure.to_dict("records"),
        "feature_ms_median": float(features_df.ms.median()),
        "feature_ms_pdf_median": float(features_df[features_df.kind == "pdf"].ms.median()),
        "feature_ms_image_median": float(features_df[features_df.kind == "image"].ms.median()),
        "struct_check_ms": STRUCT_MS,
        "struct_check_layer1_ms": STRUCT10_MS,
        "pdf_calls": pdf_calls.to_dict("records"),
    },
)

# %% [markdown]
# **What the structure rule counts.** A PDF page draws lines and shapes as vector paths. Each
# path is a list of pieces (straight lines `l`, curves `c`, rectangles `re`, four-sided shapes
# `qu`) that is then stroked (`s`), filled (`f`) or both (`fs`). A CAD export writes every
# outline, dimension line, arrowhead and shaded face as paths, while a scan or a photo saved as a
# PDF is one embedded picture with no paths. `get_drawings()` returns one entry per path on the
# page. The table shows page 1 of every PDF in the set.

# %%
pdf_structure = []
for it in pdf_items:
    with pymupdf.open(common.item_path(it)) as doc:
        paths = doc[0].get_drawings()
    pdf_structure.append(
        {
            "id": it["id"],
            "label": it["label"],
            "variant": it["variant"],
            "paths": len(paths),
            "path_types": dict(Counter(path["type"] for path in paths)),
            "pieces": dict(Counter(piece[0] for path in paths for piece in path["items"])),
            "image_cover": FEATS[it["id"]]["pdf_image_cover"],
            "chars": FEATS[it["id"]]["pdf_chars"],
        }
    )
pdf_structure_summary = (
    pd.DataFrame(pdf_structure)
    .groupby("variant")
    .agg(
        files=("id", "size"),
        paths_min=("paths", "min"),
        paths_median=("paths", "median"),
        paths_max=("paths", "max"),
        image_cover_median=("image_cover", "median"),
        chars_median=("chars", "median"),
    )
    .reset_index()
)
display(pdf_structure_summary.round(2))
common.save_json(
    "A_pdf_structure.json",
    {"files": pdf_structure, "by_variant": pdf_structure_summary.to_dict("records")},
)

# %% [markdown]
# ## Embeddings for B and C
#
# Three frozen image encoders, run with PyTorch on the M1 GPU (MPS), batch size 1 so the
# latency is what one upload would see. The input is the attachment image or page 1 of a PDF
# rendered to 1,024 px on its long side; each model's own processor then resizes it to 224 px.
#
# - CLIP ViT-B/32 (OpenAI weights through OpenCLIP, 151M parameters, MIT licence)
# - SigLIP 2 base patch16 224 (Google, 375M parameters, Apache-2.0)
# - DINOv2 small (Meta, 22M parameters, Apache-2.0); image only, so no zero-shot

# %%
import torch

DEVICE = "mps" if torch.backends.mps.is_available() else "cpu"


def load_encoder(name):
    """(embed an image, embed texts, logit scale, logit bias) for one image model."""
    if name == "clip_b32":
        import open_clip

        # pretrained="openai" resolves to timm/vit_base_patch32_clip_224.openai on the HF cache
        model, _, preprocess = open_clip.create_model_and_transforms(
            "ViT-B-32", pretrained="openai"
        )
        tokenizer = open_clip.get_tokenizer("ViT-B-32")
        model = model.to(DEVICE).eval()

        def embed_image(img):
            return model.encode_image(preprocess(img).unsqueeze(0).to(DEVICE))

        def embed_texts(texts):
            return model.encode_text(tokenizer(texts).to(DEVICE))

        return embed_image, embed_texts, float(model.logit_scale.exp()), None
    if name == "siglip2_b16":
        from transformers import AutoModel, AutoProcessor

        repo = "google/siglip2-base-patch16-224"
        model = AutoModel.from_pretrained(repo).to(DEVICE).eval()
        processor = AutoProcessor.from_pretrained(repo)

        def embed_image(img):
            out = model.get_image_features(**processor(images=img, return_tensors="pt").to(DEVICE))
            return getattr(out, "pooler_output", out)

        def embed_texts(texts):
            inputs = processor(
                text=texts, padding="max_length", max_length=64, return_tensors="pt"
            ).to(DEVICE)
            out = model.get_text_features(**inputs)
            return getattr(out, "pooler_output", out)

        return embed_image, embed_texts, float(model.logit_scale.exp()), float(model.logit_bias)
    if name == "dinov2_s":
        from transformers import AutoImageProcessor, AutoModel

        repo = "facebook/dinov2-small"
        model = AutoModel.from_pretrained(repo).to(DEVICE).eval()
        processor = AutoImageProcessor.from_pretrained(repo)

        def embed_image(img):
            return model(**processor(images=img, return_tensors="pt").to(DEVICE)).pooler_output

        return embed_image, None, None, None
    raise ValueError(name)


def unit_vector(tensor):
    return torch.nn.functional.normalize(tensor.float(), dim=-1).cpu().numpy()


def free_gpu_memory():
    gc.collect()
    if DEVICE == "mps":
        torch.mps.empty_cache()


ENCODERS = ["clip_b32", "siglip2_b16", "dinov2_s"]
EMB, EMB_STATS, TXT = {}, {}, {}
ZS_PROMPTS = {
    "drawing": [
        "a technical drawing",
        "an engineering drawing with dimensions and tolerances",
        "a CAD drawing sheet with a title block",
        "a photo of a printed engineering drawing",
    ],
    "photo": [
        "a photograph of a metal part",
        "a close-up photo of a fractured metal surface",
        "a microscope image of a metal surface",
        "a photo of a broken mechanical part",
    ],
}


def embed_all(name):
    """Embed every attachment and the zero-shot prompts, timing each image after a warm-up."""
    rss_before = common.rss_mb()
    start = time.perf_counter()
    embed_image, embed_texts, scale, bias = load_encoder(name)
    load_s = time.perf_counter() - start
    vectors, ms = {}, []
    with torch.no_grad():
        for k, it in enumerate(ATTACH):
            with common.Timer() as timer:
                vectors[it["id"]] = unit_vector(embed_image(common.attachment_image(it, 1024)))[0]
            if k >= 3:  # the first three are warm-up
                ms.append(timer.ms)
        text = None
        if embed_texts is not None:
            prompts = {c: unit_vector(embed_texts(ps)).tolist() for c, ps in ZS_PROMPTS.items()}
            text = {"emb": prompts, "scale": scale, "bias": bias}
    stats = {
        "load_s": load_s,
        "ms_median": float(np.median(ms)),
        "ms_p95": float(np.percentile(ms, 95)),
        "rss_delta_mb": common.rss_mb() - rss_before,
        "mps_driver_mb": torch.mps.driver_allocated_memory() / 1e6 if DEVICE == "mps" else None,
        "dim": int(len(next(iter(vectors.values())))),
    }
    del embed_image, embed_texts
    free_gpu_memory()
    return vectors, stats, text


for name in ENCODERS:
    path = common.RESULTS / f"emb_{name}.npz"
    if not path.exists():
        vectors, stats, text = embed_all(name)
        np.savez(
            path,
            ids=np.array(list(vectors)),
            emb=np.stack(list(vectors.values())),
            stats=json.dumps(stats),
            **({"txt": json.dumps(text)} if text else {}),
        )
    saved = np.load(path, allow_pickle=True)
    EMB[name] = dict(zip(saved["ids"], saved["emb"], strict=True))
    EMB_STATS[name] = json.loads(str(saved["stats"]))
    if "txt" in saved:
        TXT[name] = json.loads(str(saved["txt"]))
pd.DataFrame(EMB_STATS).T.round(1)

# %% [markdown]
# ## B. Linear probe on the embedding
#
# Logistic regression (scikit-learn, L2, balanced class weights) on the normalised embedding;
# class 1 is drawing. The image model stays frozen: only this regression is trained.
#
# The regularisation strength C is fixed at 100 for every probe. Over a grid from 0.1 to 100,000
# the grouped log loss keeps falling as C grows and flattens from about 1,000, because the
# drawings and photos here are easy to separate; from 100 to 10,000 it improves by about 0.01.
# A larger C also makes the probe sure of files that are neither a drawing nor a photo, so fewer
# of them escalate (the curve below). C stays at 100 for that reason, which means the choice
# looked at the files that fit no case; it should be made again on a customer's own files, with
# real examples of files that fit no case. Six checks:
#
# 1. **random half**: train on half the items, test on the other half, ignoring groups (leaky)
# 2. **grouped half**: the same, but a source sits wholly on one side; both directions are
#    reported
# 3. **leave one drawing out**: train without any page or variant of one NIST drawing, test on
#    that drawing; repeated for all 11
# 4. **leave one report out**: the same for the NTSB photo sources
# 5. **out of domain**: train on NIST and NTSB only, test on the Wikimedia Commons photos and
#    drawings, which come from other cameras, eras and drawing styles
# 6. **reverse family**: train on the 7 Commons drawings and every photo, test on the whole NIST
#    family; this is what a customer whose drawings look like no training drawing would see
#
# The out-of-fold probabilities the layered router uses come from 5 folds grouped by source.
# They are also computed with folds grouped by report page and with one source left out at a
# time, because the escalation rate depends on the grouping.


# %%
def embeddings(name, ids):
    return np.stack([EMB[name][i] for i in ids])


C_FIXED = 100.0


def new_probe():
    return LogisticRegression(C=C_FIXED, max_iter=5000, class_weight="balanced")


def c_curve(name):
    """Grouped 5-fold log loss, and how many files that fit no case stay below 0.9, for each C."""
    X, y = embeddings(name, main_ids), y_main
    X_edge = embeddings(name, [it["id"] for it in EDGE])
    curve = {}
    for c in (0.1, 1.0, 10.0, 100.0, 1000.0, 10000.0, 100000.0):
        oof = np.zeros(len(y))
        folds = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=3)
        for train, test in folds.split(X, y, groups):
            model = LogisticRegression(C=c, max_iter=5000, class_weight="balanced")
            oof[test] = model.fit(X[train], y[train]).predict_proba(X[test])[:, 1]
        model = LogisticRegression(C=c, max_iter=5000, class_weight="balanced").fit(X, y)
        p_edge = model.predict_proba(X_edge)[:, 1]
        curve[c] = {
            "log_loss": float(log_loss(y, oof)),
            "edge_below_0_9": int((np.maximum(p_edge, 1 - p_edge) < 0.9).sum()),
        }
    return curve


def held_out_accuracy(X, y, test):
    """Accuracy on the files in test of a probe trained on all the others."""
    pred = new_probe().fit(X[~test], y[~test]).predict(X[test])
    return float((pred == y[test]).mean()), pred


def expected_calibration_error(p_drawing, y):
    """The gap between confidence and accuracy, averaged over five confidence bins."""
    confidence = np.maximum(p_drawing, 1 - p_drawing)
    bins = np.linspace(0.5, 1.0, 6)
    ece = 0.0
    for lo, hi in zip(bins[:-1], bins[1:], strict=True):
        in_bin = (confidence >= lo) & (confidence < hi if hi < 1 else confidence <= hi)
        if in_bin.any():
            right = ((p_drawing[in_bin] >= 0.5) == y[in_bin]).mean()
            ece += in_bin.mean() * abs(right - confidence[in_bin].mean())
    return float(ece)


def out_of_fold(X, y, split_groups, splitter):
    """Each file's P(drawing) from a probe trained on the folds that do not hold it."""
    oof = np.zeros(len(y))
    for train, test in splitter.split(X, y, split_groups):
        oof[test] = new_probe().fit(X[train], y[train]).predict_proba(X[test])[:, 1]
    return oof


def run_probe(name):
    X, y = embeddings(name, main_ids), y_main
    sources = np.array([it["source"] for it in MAIN])
    out = {"C": C_FIXED, "c_curve": c_curve(name)}
    for tag, splits in (("random_half", RANDOM_HALF), ("grouped_half", HALF)):
        out[tag] = [
            float((new_probe().fit(X[train], y[train]).predict(X[test]) == y[test]).mean())
            for train, test in splits
        ]

    by_drawing, wrong = {}, []
    for drawing in sorted({it["group"] for it in MAIN if it["source"] == "nist"}):
        test = groups == drawing
        by_drawing[drawing], pred = held_out_accuracy(X, y, test)
        wrong += [main_ids[i] for i in np.where(test)[0][pred != y[test]]]
    out["lodo_mean"] = float(np.mean(list(by_drawing.values())))
    out["lodo_min"] = float(min(by_drawing.values()))
    out["lodo"] = by_drawing
    out["lodo_wrong"] = wrong

    out["loro"] = {
        report: held_out_accuracy(X, y, sources == report)[0]
        for report in sorted({s for s in sources if s.startswith("ntsb")})
    }

    test = sources == "commons"
    out["ood_commons"], pred = held_out_accuracy(X, y, test)
    out["ood_wrong"] = [main_ids[i] for i in np.where(test)[0][pred != y[test]]]

    # reverse family: train on the Commons drawings and every photo, score the NIST family
    test = sources == "nist"
    p_nist = new_probe().fit(X[~test], y[~test]).predict_proba(X[test])[:, 1]
    wrong_nist = (p_nist >= 0.5) != y[test]
    out["reverse_nist"] = {
        "n": int(test.sum()),
        "wrong": int(wrong_nist.sum()),
        "below_0_9": int((np.maximum(p_nist, 1 - p_nist) < 0.9).sum()),
        "wrong_ids": [main_ids[i] for i in np.where(test)[0][wrong_nist]],
    }

    # out-of-fold probabilities for the layered router, under three groupings
    five_folds = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=11)
    oof = out_of_fold(X, y, groups, five_folds)
    out["oof_by_grouping"] = {
        "page": dict(
            zip(main_ids, out_of_fold(X, y, groups_page, five_folds).tolist(), strict=True)
        ),
        "loso": dict(
            zip(main_ids, out_of_fold(X, y, groups, LeaveOneGroupOut()).tolist(), strict=True)
        ),
    }
    out["oof_acc"] = float(((oof >= 0.5) == y).mean())
    out["oof_wrong"] = [main_ids[i] for i in np.where((oof >= 0.5) != y)[0]]
    out["oof_p_drawing"] = dict(zip(main_ids, oof.tolist(), strict=True))
    out["brier"] = float(np.mean((oof - y) ** 2))
    out["ece"] = expected_calibration_error(oof, y)

    # the files that fit no case, scored by a probe trained on every drawing and photo (the
    # weights a router would ship), and that probe's lowest confidence on its own training files
    full = new_probe().fit(X, y)
    p_edge = full.predict_proba(embeddings(name, [it["id"] for it in EDGE]))[:, 1]
    out["edge"] = {it["id"]: float(p) for it, p in zip(EDGE, p_edge, strict=True)}
    p_train = full.predict_proba(X)[:, 1]
    out["in_sample_min_conf"] = float(np.maximum(p_train, 1 - p_train).min())

    # training and inference time, measured once and cached like the other timings
    if "fit_ms" in PROBE_TIMES.get(name, {}):
        out["fit_ms"] = PROBE_TIMES[name]["fit_ms"]
        out["predict_ms"] = PROBE_TIMES[name]["predict_ms"]
        return out
    start = time.perf_counter()
    full = new_probe().fit(X, y)
    out["fit_ms"] = (time.perf_counter() - start) * 1000
    start = time.perf_counter()
    for _ in range(200):
        full.predict_proba(X[:1])
    out["predict_ms"] = (time.perf_counter() - start) * 1000 / 200
    return out


PROBE_TIMES = common.load_json("B_probe.json") or {}
PROBES = {name: run_probe(name) for name in ENCODERS}
common.save_json("B_probe.json", PROBES)
print("log loss and edge files below 0.9 by C:")
display(
    pd.DataFrame(
        {
            (name, metric): {c: v[metric] for c, v in probe["c_curve"].items()}
            for name, probe in PROBES.items()
            for metric in ("log_loss", "edge_below_0_9")
        }
    ).round(4)
)
pd.DataFrame(
    {
        name: {
            "C": probe["C"],
            "random half (leaky)": np.mean(probe["random_half"]),
            "grouped half 0->1": probe["grouped_half"][0],
            "grouped half 1->0": probe["grouped_half"][1],
            "leave one drawing out, mean": probe["lodo_mean"],
            "leave one drawing out, worst": probe["lodo_min"],
            **{f"leave out {k}": v for k, v in probe["loro"].items()},
            "out of domain (Commons)": probe["ood_commons"],
            "reverse: NIST wrong": probe["reverse_nist"]["wrong"],
            "reverse: NIST below 0.9": probe["reverse_nist"]["below_0_9"],
            "5-fold grouped OOF": probe["oof_acc"],
            "Brier": probe["brier"],
            "ECE": probe["ece"],
            "embed ms (MPS)": EMB_STATS[name]["ms_median"],
            "probe ms": probe["predict_ms"],
        }
        for name, probe in PROBES.items()
    }
).round(3)

# %%
for name, probe in PROBES.items():
    print(
        name,
        "| OOF wrong:",
        probe["oof_wrong"],
        "| OOD wrong:",
        probe["ood_wrong"],
        "| LODO wrong:",
        probe["lodo_wrong"],
    )
    print("   edge p(drawing):", {k: round(v, 2) for k, v in probe["edge"].items()})

# %% [markdown]
# ## C. Zero-shot with text prompts
#
# No training. Each class is described by four prompts; the image is assigned to the class
# whose mean prompt embedding is closest. CLIP turns the similarities into a softmax with its
# learned temperature; SigLIP 2 scores each prompt with its own sigmoid and we compare the class
# means. The prompts include "a photo of a printed engineering drawing" because a phone photo
# of a sheet must still route to the drawing case.


# %%
def zero_shot(name):
    """Each attachment's P(drawing) from its similarity to the prompts of each class."""
    text = TXT[name]
    prompts = {c: np.array(text["emb"][c]) for c in ZS_PROMPTS}
    out = {}
    for it in ATTACH:
        vector = EMB[name][it["id"]]
        if name.startswith("siglip"):
            sigmoid = {
                c: float(
                    np.mean(1 / (1 + np.exp(-(text["scale"] * prompts[c] @ vector + text["bias"]))))
                )
                for c in prompts
            }
            total = sum(sigmoid.values())
            out[it["id"]] = sigmoid["drawing"] / total if total > 0 else 0.5
        else:
            logits = np.array([np.mean(text["scale"] * prompts[c] @ vector) for c in prompts])
            softmax = np.exp(logits - logits.max())
            out[it["id"]] = float(softmax[0] / softmax.sum())
    return out


ZERO_SHOT = {}
truth_main = [it["label"] for it in MAIN]
for name in ("clip_b32", "siglip2_b16"):
    p_drawing = zero_shot(name)
    pred = [label_of(p_drawing[i]) for i in main_ids]
    ZERO_SHOT[name] = {
        "acc": accuracy(truth_main, pred),
        "p_drawing": p_drawing,
        "wrong": [i for i, a, b in zip(main_ids, truth_main, pred, strict=True) if a != b],
        "confusion": common.confusion(truth_main, pred, rows=("drawing", "photo")),
    }
common.save_json("C_zeroshot.json", ZERO_SHOT)
for name, result in ZERO_SHOT.items():
    print(f"{name}: accuracy {result['acc']:.3f}; confusion {result['confusion']}")
    print("   wrong:", result["wrong"])

# %% [markdown]
# ## G. A pretrained document-figure classifier (Docling)
#
# Docling's DocumentFigureClassifier v2.5 is an EfficientNet-B0 (4M parameters, 34 MB, MIT
# licence) trained to sort figures cut out of PDFs into 26 classes, two of which are
# `engineering_drawing` and `photograph`. It needs no training from us. We map
# `engineering_drawing` to drawing, `photograph` to photo, and the other 24 classes to other,
# and take the group with the highest summed probability. Its 1,280-number pooled features are
# also tried as a fourth embedding for the linear probe.

# %%
docling_path = common.RESULTS / "G_docling.json"
docling_features_path = common.RESULTS / "emb_docling_fig.npz"
if not docling_path.exists():
    import torchvision.transforms as T
    from transformers import EfficientNetForImageClassification

    repo = "docling-project/DocumentFigureClassifier-v2.5"
    figure_model = EfficientNetForImageClassification.from_pretrained(repo).to(DEVICE).eval()
    to_input = T.Compose(
        [
            T.Resize((224, 224)),
            T.ToTensor(),
            T.Normalize([0.485, 0.456, 0.406], [0.47853944, 0.4732864, 0.47434163]),
        ]
    )
    class_names = figure_model.config.id2label
    docling_items, features, ms = {}, {}, []
    with torch.no_grad():
        for k, it in enumerate(ATTACH):
            with common.Timer() as timer:
                x = to_input(common.attachment_image(it, 1024)).unsqueeze(0).to(DEVICE)
                hidden = figure_model.efficientnet(x).pooler_output
                probs = figure_model.classifier(hidden).softmax(-1).float().cpu().numpy()[0]
            if k >= 3:  # the first three are warm-up
                ms.append(timer.ms)
            ranked = sorted(
                ((class_names[i], float(p)) for i, p in enumerate(probs)), key=lambda pair: -pair[1]
            )
            docling_items[it["id"]] = {
                "probs": {class_names[i]: float(p) for i, p in enumerate(probs)},
                "top": ranked[:3],
            }
            features[it["id"]] = unit_vector(hidden)[0]
    docling_stats = {
        "ms_median": float(np.median(ms)),
        "ms_p95": float(np.percentile(ms, 95)),
        "mps_driver_mb": torch.mps.driver_allocated_memory() / 1e6 if DEVICE == "mps" else None,
    }
    docling_path.write_text(json.dumps({"items": docling_items, "stats": docling_stats}))
    np.savez(
        docling_features_path,
        ids=np.array(list(features)),
        emb=np.stack(list(features.values())),
        stats=json.dumps({**docling_stats, "dim": 1280}),
    )
    del figure_model
    free_gpu_memory()
DOCLING_RAW = json.loads(docling_path.read_text())


def docling_route(probs):
    """drawing, photo or other, whichever has the largest summed probability."""
    drawing = probs["engineering_drawing"]
    photo = probs["photograph"]
    return max(
        (("drawing", drawing), ("photo", photo), ("other", 1 - drawing - photo)),
        key=lambda pair: pair[1],
    )[0]


def docling_two_way(probs):
    return "drawing" if probs["engineering_drawing"] >= probs["photograph"] else "photo"


docling_probs = {i: DOCLING_RAW["items"][i]["probs"] for i in DOCLING_RAW["items"]}
docling_pred = [docling_route(docling_probs[i]) for i in main_ids]
DOCLING = {
    "acc_3way": accuracy(truth_main, docling_pred),
    "acc_2way": accuracy(truth_main, [docling_two_way(docling_probs[i]) for i in main_ids]),
    "confusion": common.confusion(truth_main, docling_pred, rows=("drawing", "photo")),
    "wrong": [
        (i, DOCLING_RAW["items"][i]["top"][0])
        for i, a, b in zip(main_ids, truth_main, docling_pred, strict=True)
        if a != b
    ],
    "edge": {it["id"]: DOCLING_RAW["items"][it["id"]]["top"][0] for it in EDGE},
    **DOCLING_RAW["stats"],
}
common.save_json("G_summary.json", DOCLING)
print(
    f"3-way accuracy {DOCLING['acc_3way']:.3f}, drawing-or-photo only {DOCLING['acc_2way']:.3f}, "
    f"{DOCLING['ms_median']:.1f} ms per image"
)
print("confusion:", DOCLING["confusion"])
print("top class of the mistakes:", DOCLING["wrong"])
print("edge items:", DOCLING["edge"])

# %% [markdown]
# The Docling features as a fourth probe, with the same checks as section B.

# %%
saved = np.load(docling_features_path, allow_pickle=True)
EMB["docling_fig"] = dict(zip(saved["ids"], saved["emb"], strict=True))
EMB_STATS["docling_fig"] = json.loads(str(saved["stats"]))
ENCODERS.append("docling_fig")
PROBES["docling_fig"] = run_probe("docling_fig")
common.save_json("B_probe.json", PROBES)
probe = PROBES["docling_fig"]
shown = (
    "C",
    "random_half",
    "grouped_half",
    "lodo_mean",
    "lodo_min",
    "loro",
    "ood_commons",
    "oof_acc",
    "brier",
    "ece",
)
print({k: probe[k] for k in shown})
print("OOF wrong:", probe["oof_wrong"], "OOD wrong:", probe["ood_wrong"])

# %% [markdown]
# ## D and F. A local model asked one question
#
# `run_models.py` runs each model in its own process (so peak memory is its own) over every
# attachment, resized to 768 px on the long side, with three options: drawing, photo, or other
# (a page of text, a logo, a chart). For the 10 messages sent with an attachment it asks twice:
# once with the image alone and once with the user's message in the prompt, to see whether a
# misleading message sways the answer.
#
# - **D**, general vision-language models: Qwen3-VL 2B, 4B and 8B Instruct, MLX 4-bit
#   (Apache-2.0). The question lists the options as letters A, B and C; the probability of each
#   option is the softmax of the first answer token's log-probabilities over those three letters.
# - **F**, open-weight decision models: LiquidAI d1-omni-600M (8-bit), d1-2B and d1-3B (4-bit),
#   licence LFM Open License v1.0. They are built for typed choices: mlx-vlm's `decision.predict`
#   takes the named options with a description each and returns a probability per option
#   without generating text. This is the local counterpart of hosted decision APIs such as
#   Typesafe's Jev or OpenAI's Decisions API.
#
# Four files were added to the set after these models ran (the drawing package, the OCRed
# drawing, and the scanned report page with and without OCR), and the models were not run again:
# each needs a 2 to 7 GB load. Each model is scored on the files it answered (`scored`), and
# `not_run` lists the rest.

# %%
VLMS = {
    "qwen3vl_2b": "D",
    "qwen3vl_4b": "D",
    "qwen3vl_8b": "D",
    "d1_omni_600m": "F",
    "d1_2b": "F",
    "d1_3b": "F",
}
MODEL_RES = {}
for name in VLMS:
    if common.load_json(f"model_{name}.json") is None:  # about ten minutes per model
        subprocess.run([sys.executable, str(HERE / "run_models.py"), name], check=True)
    MODEL_RES[name] = common.load_json(f"model_{name}.json")


def model_ece(confidence, correct, bins=5):
    """Expected calibration error over three options, so the bins start at about 1/3."""
    confidence, correct = np.asarray(confidence), np.asarray(correct, float)
    edges = np.linspace(min(confidence.min(), 0.34), 1.0, bins + 1)
    ece = 0.0
    for lo, hi in zip(edges[:-1], edges[1:], strict=True):
        in_bin = (confidence >= lo) & ((confidence < hi) if hi < 1 else (confidence <= hi))
        if in_bin.any():
            ece += in_bin.mean() * abs(correct[in_bin].mean() - confidence[in_bin].mean())
    return float(ece)


def model_scores(name):
    answers = MODEL_RES[name]["items"]
    ids = [i for i in main_ids if i in answers]
    truth = [BY_ID[i]["label"] for i in ids]
    pred = [answers[i]["pred"] for i in ids]
    confidence = [max(answers[i]["p"].values()) for i in ids]
    right = [a == b for a, b in zip(truth, pred, strict=True)]
    pair_truth = [it["label"] for it in PAIRS]
    with_text = [MODEL_RES[name]["pairs"][it["id"]]["pred"] for it in PAIRS]
    image_only = [answers[it["attachment"]]["pred"] for it in PAIRS]
    wrong_confidence = [c for c, ok in zip(confidence, right, strict=True) if not ok]
    return {
        "approach": VLMS[name],
        "acc": float(np.mean(right)),
        "confusion": common.confusion(truth, pred, rows=("drawing", "photo")),
        "scored": len(ids),
        "not_run": [it["id"] for it in ATTACH if it["id"] not in answers],
        "wrong": [
            (i, answers[i]["pred"], round(max(answers[i]["p"].values()), 3))
            for i, ok in zip(ids, right, strict=True)
            if not ok
        ],
        "ece": model_ece(confidence, right),
        "mean_conf_when_wrong": float(np.mean(wrong_confidence)) if wrong_confidence else None,
        "pairs_acc_image_only": accuracy(pair_truth, image_only),
        "pairs_acc_with_text": accuracy(pair_truth, with_text),
        "pairs_flipped_by_text": [
            it["id"] for it, a, b in zip(PAIRS, image_only, with_text, strict=True) if a != b
        ],
        "edge": {it["id"]: answers[it["id"]]["pred"] for it in EDGE if it["id"] in answers},
        **MODEL_RES[name]["stats"],
    }


MODEL_SCORES = {name: model_scores(name) for name in VLMS}
common.save_json("DF_models.json", MODEL_SCORES)
lists = ("confusion", "wrong", "edge", "pairs_flipped_by_text", "not_run")
pd.DataFrame(
    {
        name: {k: v for k, v in scores.items() if k not in lists}
        for name, scores in MODEL_SCORES.items()
    }
).T.round(3)

# %%
for name, scores in MODEL_SCORES.items():
    print(f"{name} ({scores['approach']}): confusion {scores['confusion']}")
    print("   wrong:", scores["wrong"])
    print("   flipped by the user's text:", scores["pairs_flipped_by_text"])
    print("   edge items:", scores["edge"])

# %% [markdown]
# ## E. The layered router
#
# Layer 1 is the structure-only rules (no attachment, vector PDF or drawing package, prose PDF).
# What they leave undecided goes to layer 2, a linear probe whose probability comes from the
# out-of-fold predictions above, so no item is scored by a probe that saw its drawing, its report
# or its Commons file. When the probe's confidence max(p, 1 - p) is below the threshold t, layer 3
# asks a local model and takes its answer, which may also be "other". The user's text is not
# shown to the router; the effect of showing it is measured separately above.
#
# Every file is counted once: a message with an attachment repeats a file that is already in the
# set, and the router ignores the message, so the pairs are checked to route like their files and
# then left out of the counts. Scores are over the 224 labelled requests (204 drawing and photo
# files and 20 questions); the 10 files that fit no case are reported apart.
#
# The times are reconstructed, not measured end to end: each request gets the measured cost of
# every layer it passed through. That is the layer-1 check of that PDF (section A), or a 1 ms
# allowance for an image's file-type check, then the embedding median and the probe time
# (section B), then that file's own model call when it escalates.
#
# The escalation rate depends on how the probe's folds are grouped, so every summary is computed
# three ways: 5 folds grouped by source (the default), 5 folds grouped by report page, and
# leaving one source out at a time.

# %%
LAYER1 = {
    "structural": dict(zip(rules_structure.id, rules_structure.decision, strict=True)),
    "full": dict(zip(rules_exif.id, rules_exif.decision, strict=True)),
    # no layer 1 beyond "no attachment is text": every attachment goes to the probe
    "none": {it["id"]: "text" if it["kind"] == "text" else "undecided" for it in ITEMS},
}
GROUPINGS = ("report", "page", "loso")  # report: 5 folds by source, the default
PROBE_P = {
    grouping: {
        name: {
            **(
                PROBES[name]["oof_p_drawing"]
                if grouping == "report"
                else PROBES[name]["oof_by_grouping"][grouping]
            ),
            **PROBES[name]["edge"],
        }
        for name in ENCODERS
    }
    for grouping in GROUPINGS
}


def file_of(it):
    """The item whose file a request sends."""
    return it["attachment"] if it["variant"] == "text_pair" else it["id"]


def layer1_ms(it, rules):
    features = FEATS[it["id"]]
    if features["kind"] == "text":
        return 0.0
    if rules == "none":
        return 1.0  # a file-type check only; a PDF page is rendered inside the embedding time
    if rules == "structural":
        # a file-type check for an image; the measured layer-1 check of that PDF
        return 1.0 if features["kind"] == "image" else STRUCT10_MS[file_of(it)]
    return features["ms"]


def layered(encoder, model, threshold, rules="structural", grouping="report"):
    """Every item routed through the layers: its final answer, the stage that gave it and the
    reconstructed time. A threshold above 1 skips the probe, so every file goes to the model."""
    rows = []
    for it in ITEMS:
        decision = LAYER1[rules][it["id"]]
        ms = layer1_ms(it, rules)
        stage = "A"
        if decision == "undecided":
            stage = "B"
            if threshold <= 1:
                p_drawing = PROBE_P[grouping][encoder][file_of(it)]
                ms += EMB_STATS[encoder]["ms_median"] + PROBES[encoder]["predict_ms"]
                if max(p_drawing, 1 - p_drawing) >= threshold:
                    decision = label_of(p_drawing)
            if decision == "undecided":
                stage = "D"
                answer = MODEL_RES[model]["items"].get(file_of(it))
                if answer is None:  # a file the model was not run on
                    decision = "not run"
                else:
                    decision = answer["pred"]
                    ms += answer["ms"]
        rows.append(
            {
                "id": it["id"],
                "label": it["label"],
                "variant": it["variant"],
                "final": decision,
                "stage": stage,
                "ms": ms,
            }
        )
    return pd.DataFrame(rows)


def layered_summary(df):
    final = dict(zip(df.id, df.final, strict=True))
    for it in PAIRS:  # the router ignores the message, so a pair routes like its file
        assert final[it["id"]] == final[it["attachment"]], it["id"]
    df = df[df.variant != "text_pair"]  # count every file once
    labelled = df[df.label != "other"]
    files = labelled[labelled.variant != "text_only"]  # the unique drawing and photo files
    edge = df[df.label == "other"]
    measured = labelled[labelled.final != "not run"]
    return {
        "labelled": len(labelled),
        "attachments": len(files),
        "acc_all": float((measured.final == measured.label).mean()),
        "acc_attachments": float((files.final == files.label).mean()),
        "errors": int((measured.final != measured.label).sum()),
        "not_run": int((df.final == "not run").sum()),
        "not_run_labelled": int((labelled.final == "not run").sum()),
        "not_run_edge": int((edge.final == "not run").sum()),
        "share_A": float((files.stage == "A").mean()),
        "share_B": float((files.stage == "B").mean()),
        "escalated": float((files.stage == "D").mean()),
        "escalated_n": int((files.stage == "D").sum()),
        "ms_mean_attachment": float(files.ms.mean()),
        "ms_median_attachment": float(files.ms.median()),
        "ms_p95_attachment": float(files.ms.quantile(0.95)),
        "edge": len(edge),
        "edge_not_forced": int(edge.final.isin(["other", "document"]).sum()),
    }


THRESHOLDS = [0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.98, 0.99, 0.995]
sweep = []
for grouping in GROUPINGS:
    for encoder in ENCODERS:
        for model in VLMS:
            for threshold in THRESHOLDS:
                summary = layered_summary(layered(encoder, model, threshold, grouping=grouping))
                sweep.append(
                    {"grouping": grouping, "encoder": encoder, "model": model, "t": threshold}
                    | summary
                )
SWEEP = pd.DataFrame(sweep)
common.save_json("E_sweep.json", SWEEP.to_dict("records"))
REC_SWEEP = SWEEP[(SWEEP.encoder == "dinov2_s") & (SWEEP.model == "qwen3vl_8b")]
REC_SWEEP.pivot(index="t", columns="grouping", values="escalated").round(3)

# %%
DEFAULT_GROUPING = SWEEP[SWEEP.grouping == "report"]
print("The recommended router at each threshold (5 folds grouped by source):")
display(
    REC_SWEEP[REC_SWEEP.grouping == "report"][
        ["t", "errors", "escalated", "ms_mean_attachment", "edge_not_forced"]
    ].round(3)
)
print("Every encoder with Qwen3-VL 8B as layer 3, at t = 0.9, under each grouping:")
display(
    SWEEP[(SWEEP.model == "qwen3vl_8b") & (SWEEP.t == 0.9)]
    .pivot(index="encoder", columns="grouping", values="escalated")
    .round(3)
)
print("Every layer-3 model behind DINOv2 at t = 0.9:")
display(
    DEFAULT_GROUPING[(DEFAULT_GROUPING.encoder == "dinov2_s") & (DEFAULT_GROUPING.t == 0.9)].round(
        3
    )
)

# %% [markdown]
# For contrast, the same router with the full pixel rules (EXIF, white and flat shares) as
# layer 1: every photographed drawing is decided wrongly before the classifier sees it.

# %%
pd.DataFrame(
    [
        {
            "encoder": "dinov2_s",
            "model": model,
            "t": 0.9,
            **layered_summary(layered("dinov2_s", model, 0.9, rules="full")),
        }
        for model in ("d1_omni_600m", "qwen3vl_8b")
    ]
).round(3)

# %% [markdown]
# **Why not one model alone.** The DINOv2 probe made no mistake on the drawings and photos, so
# the simplest router is the probe plus "no attachment is text". At a threshold of 0.5 nothing
# escalates, so these rows compare the probe alone, the probe behind the structure rules, the
# probe with the third layer, and the recommended router with both. The decision model d1-2B can
# answer "other" itself, so it is also tried alone and behind the structure rules, with no probe
# (a threshold above 1 sends every file to the model).

# %%
simpler = []
for router, rules, threshold, model in [
    ("probe alone", "none", 0.5, "qwen3vl_8b"),
    ("structure rules and probe", "structural", 0.5, "qwen3vl_8b"),
    ("probe and Qwen3-VL 8B below 0.9", "none", 0.9, "qwen3vl_8b"),
    ("recommended", "structural", 0.9, "qwen3vl_8b"),
    ("d1-2B alone", "none", 1.01, "d1_2b"),
    ("structure rules and d1-2B", "structural", 1.01, "d1_2b"),
]:
    df = layered("dinov2_s", model, threshold, rules=rules)
    edge = df[df.label == "other"]
    simpler.append(
        {
            "router": router,
            "rules": rules,
            "t": threshold,
            "model": model,
            **layered_summary(df),
            "edge_final": dict(zip(edge.id, edge.final, strict=True)),
        }
    )
display(pd.DataFrame(simpler).drop(columns="edge_final").round(3))
common.save_json("E_simpler.json", simpler)

# %% [markdown]
# ## Errors of the recommended configuration

# %%
REC = {"encoder": "dinov2_s", "model": "qwen3vl_8b", "t": 0.9}
rec_df = layered(REC["encoder"], REC["model"], REC["t"])
print(layered_summary(rec_df))
display(pd.crosstab(rec_df.label, rec_df.final, margins=True))
display(rec_df[rec_df.label != rec_df.final])
display(rec_df[rec_df.stage == "D"])

# %% [markdown]
# What each layer of the recommended router decided, over the 234 unique requests (the 10 pairs
# route like their files and are left out). "Reached" counts the requests the earlier layers
# passed on. The time is the reconstructed cost of a request that ends at that layer, earlier
# layers included, split by what the request carried.


# %%
def input_of(item_id):
    kind = BY_ID[item_id]["kind"]
    return "none" if kind == "text" else ("pdf" if kind.endswith("pdf") else "image")


def layer_table(df):
    df = df[df.variant != "text_pair"]
    rows, reached = [], len(df)
    for stage in ("A", "B", "D"):
        decided = df[df.stage == stage]
        labelled = decided[decided.label != "other"]
        edge = decided[decided.label == "other"]
        rows.append(
            {
                "stage": stage,
                "reached": reached,
                "decided": len(decided),
                "decided_as": dict(Counter(decided.final)),
                "labelled": len(labelled),
                "wrong": int((labelled.final != labelled.label).sum()),
                "edge": len(edge),
                "edge_forced": int(edge.final.isin(["drawing", "photo"]).sum()),
                "ms_median": float(decided.ms.median()),
                "ms_min": float(decided.ms.min()),
                "ms_max": float(decided.ms.max()),
                "ms_median_by_input": {
                    k: float(v)
                    for k, v in decided.groupby(decided.id.map(input_of)).ms.median().items()
                },
                "ids": list(decided.id) if stage == "D" else [],
            }
        )
        reached -= len(decided)
    return rows


rec_layers = layer_table(rec_df)
display(pd.DataFrame(rec_layers).drop(columns="ids"))
unique_df = rec_df[rec_df.variant != "text_pair"]
rec_files = unique_df[unique_df.id.map(input_of) != "none"]
rec_totals = {
    "requests": len(unique_df),
    "attachments": len(rec_files),
    "attachments_escalated": int((rec_files.stage == "D").sum()),
    "ms_mean_all_attachments": float(rec_files.ms.mean()),
}
print(rec_totals)

# %% [markdown]
# **How much the escalation rate depends on the grouping**, and what that means at a million
# files: the escalated share times a million, times Qwen3-VL 8B's median time per image over
# all items, and the probe's embedding time for every file.

# %%
SCALE = 1_000_000
qwen_s = MODEL_SCORES[REC["model"]]["ms_median"] / 1000
rec_range = {}
for grouping in GROUPINGS:
    df = layered(REC["encoder"], REC["model"], REC["t"], grouping=grouping)
    summary = layered_summary(df)
    rec_range[grouping] = summary | {
        "escalated_ids": list(
            df.query("stage == 'D' and label in ('drawing', 'photo') and variant != 'text_pair'").id
        ),
        "million_escalated": summary["escalated"] * SCALE,
        "million_layer3_hours": summary["escalated"] * SCALE * qwen_s / 3600,
    }
rec_scale = {
    "probe_hours_per_million": SCALE * EMB_STATS[REC["encoder"]]["ms_median"] / 1000 / 3600,
    "qwen_s_per_image": qwen_s,
}
shown = [
    "escalated_n",
    "escalated",
    "ms_mean_attachment",
    "million_layer3_hours",
    "edge_not_forced",
]
display(pd.DataFrame(rec_range).T[shown])
print(rec_scale)
common.save_json(
    "E_recommended.json",
    {
        "config": REC,
        "summary": layered_summary(rec_df),
        "by_grouping": rec_range,
        "scale": rec_scale,
        "layers": rec_layers,
        "totals": rec_totals,
        "confusion": pd.crosstab(rec_df.label, rec_df.final).to_dict(),
        "rows": rec_df.to_dict("records"),
    },
)

# %% [markdown]
# ## Summary table
#
# One row per approach, as used in the write-up. Accuracy is on the 204 drawing and photo files
# (messages with an attachment counted once, through their file); a decision of "undecided" or
# "other" counts as wrong. Precision for a case is the share of the files an option sent to that
# case that belong there, and recall is the share of that case's files it sent there, so an
# undecided or "other" answer lowers recall but not precision. Latency is the median per file on
# the M1 Pro.


# %%
def precision_recall(truth, pred):
    """Precision and recall of the drawing and photo cases."""
    out = {}
    for case in ("drawing", "photo"):
        called = [t for t, q in zip(truth, pred, strict=True) if q == case]
        actual = [q for t, q in zip(truth, pred, strict=True) if t == case]
        out[f"{case}_precision"] = sum(t == case for t in called) / len(called) if called else None
        out[f"{case}_recall"] = sum(q == case for q in actual) / len(actual)
    return out


def rules_row(name, decisions, ms):
    df = decisions[decisions.id.isin(main_ids)]
    decided = df[df.decision.isin(["drawing", "photo"])]
    return {
        "approach": name,
        "accuracy": float((df.decision == df.label).mean()),
        "coverage": float(len(decided) / len(df)),
        "precision_when_decided": float((decided.decision == decided.label).mean()),
        **precision_recall(list(df.label), list(df.decision)),
        "ms_median": ms,
        "memory_mb": None,
        "probability": "no",
    }


cad_pdf_ms = float(np.median([STRUCT10_MS[it["id"]] for it in pdf_items if it["variant"] == "pdf"]))
rows = [
    rules_row("A rules with EXIF", rules_exif, float(features_df.ms.median())),
    rules_row("A rules without EXIF", rules_no_exif, float(features_df.ms.median())),
    # the layer-1 check on the CAD PDFs it decides (an image only needs its file type)
    rules_row("A structure only", rules_structure, cad_pdf_ms),
]
for name in ENCODERS:
    oof_pred = [label_of(PROBES[name]["oof_p_drawing"][i]) for i in main_ids]
    rows.append(
        {
            "approach": f"B probe on {name}",
            "accuracy": PROBES[name]["oof_acc"],
            **precision_recall(truth_main, oof_pred),
            "ood_commons": PROBES[name]["ood_commons"],
            "lodo_mean": PROBES[name]["lodo_mean"],
            "coverage": 1.0,
            "ms_median": EMB_STATS[name]["ms_median"],
            "memory_mb": EMB_STATS[name]["mps_driver_mb"],
            "probability": f"yes (ECE {PROBES[name]['ece']:.3f})",
        }
    )
for name in ("clip_b32", "siglip2_b16"):
    pred = [label_of(ZERO_SHOT[name]["p_drawing"][i]) for i in main_ids]
    rows.append(
        {
            "approach": f"C zero-shot {name}",
            "accuracy": ZERO_SHOT[name]["acc"],
            **precision_recall(truth_main, pred),
            "coverage": 1.0,
            "ms_median": EMB_STATS[name]["ms_median"],
            "memory_mb": EMB_STATS[name]["mps_driver_mb"],
            "probability": "softmax or sigmoid score",
        }
    )
rows.append(
    {
        "approach": "G Docling figure classifier",
        "accuracy": DOCLING["acc_3way"],
        **precision_recall(truth_main, docling_pred),
        "coverage": 1.0,
        "ms_median": DOCLING["ms_median"],
        "memory_mb": DOCLING["mps_driver_mb"],
        "probability": "softmax over 26 classes",
    }
)
for name, scores in MODEL_SCORES.items():
    answers = MODEL_RES[name]["items"]
    ids = [i for i in main_ids if i in answers]
    rows.append(
        {
            "approach": f"{scores['approach']} {name}",
            "accuracy": scores["acc"],
            "scored": scores["scored"],
            **precision_recall([BY_ID[i]["label"] for i in ids], [answers[i]["pred"] for i in ids]),
            "coverage": 1.0,
            "ms_median": scores["ms_median"],
            "memory_mb": scores["peak_mlx_gb"] * 1000,
            "probability": f"yes (ECE {scores['ece']:.3f})",
        }
    )
rec_summary = layered_summary(rec_df)
rec_main = rec_df[rec_df.id.isin(main_ids)]
rows.append(
    {
        "approach": "E layered (structure, DINOv2 probe, Qwen3-VL 8B at t=0.9)",
        "accuracy": rec_summary["acc_attachments"],
        **precision_recall(list(rec_main.label), list(rec_main.final)),
        "coverage": 1.0,
        "ms_median": rec_summary["ms_median_attachment"],
        "escalated": rec_summary["escalated"],
        "probability": "yes",
    }
)
SUMMARY = pd.DataFrame(rows)
common.save_json("summary.json", SUMMARY.to_dict("records"))
SUMMARY.round(3)
