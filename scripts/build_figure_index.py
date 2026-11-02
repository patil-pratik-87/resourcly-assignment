"""Cut the NTSB reports into figures and write the figure index a failure finder version names.

    uv run --extra router python scripts/build_figure_index.py \\
        --encoder-model facebook/dinov2-base --out versions/failure/indexes/dinov2-base-v1.json

Every figure of every PDF in the reports folder (data/reports/ by default) is rendered, labelled
with its section and failure mode from sections.toml and embedded with the encoder. The index
records the encoder, its vector recipe and input size, and a finder whose encoder differs refuses
to load it. A version's hash covers its index, so write a new file under a new name rather than
overwriting one that a version uses.
"""

import argparse
from pathlib import Path

from resourcly.adapters.figure_index import build_index
from resourcly.bootstrap import ENCODERS, Settings
from resourcly.progress import progress_bar


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, required=True, help="The index JSON file to write.")
    parser.add_argument("--encoder", default="dinov2", choices=sorted(ENCODERS))
    parser.add_argument("--encoder-model", default="facebook/dinov2-base")
    parser.add_argument("--recipe", default="cls_patch_mean", help="How a vector is made.")
    parser.add_argument("--input-size", type=int, default=224, help="The square the model sees.")
    parser.add_argument("--max-side", type=int, default=1024, help="Picture size for the encoder.")
    parser.add_argument("--dpi", type=int, default=150, help="The figures' render resolution.")
    args = parser.parse_args()
    settings = Settings.from_env()
    encoder = ENCODERS[args.encoder](
        args.encoder_model, args.max_side, recipe=args.recipe, input_size=args.input_size
    )
    reports = sorted(settings.reports_dir.glob("*.pdf"))
    print(f"cutting {len(reports)} reports in {settings.reports_dir} into figures")
    print(f"embedding each with {args.encoder_model}; the model loads on the first figure")
    with progress_bar() as bar:
        task = bar.add_task("reports", total=len(reports))

        def done(report: str, figures: int) -> None:
            bar.advance(task)
            print(f"{report}: {figures} figures embedded")

        index = build_index(
            settings.reports_dir, settings.reports_dir / "sections.toml", encoder, args.dpi, done
        )
    index.save(args.out)
    print(
        f"wrote {args.out}: {len(index.figures)} figures from {len(index.reports)} reports,"
        f" vectors of {len(index.figures[0].vector)} from {index.encoder_model}"
    )


if __name__ == "__main__":
    main()
