"""Render a drawing page (or a region of it) with a labelled grid in page fractions.

Gold bboxes are fractions of the page as displayed. The NIST PDFs carry a 270 degree page rotation,
and PyMuPDF's clip rectangle is in that displayed frame, so grid lines here match bbox values
directly.

    uv run python scripts/gold_tools/grid.py nist_ctc_01_asme1_rd
    uv run python scripts/gold_tools/grid.py nist_ctc_01_asme1_rd \
        --region 0.39 0.09 0.47 0.16 --dpi 400 --step 0.01
"""

import argparse
import math

import pymupdf

from common import OUT, open_drawing, out_dir


def render_grid(page, region, dpi, step):
    x0, y0, x1, y1 = region
    width, height = page.rect.width, page.rect.height
    pix = page.get_pixmap(
        dpi=dpi, clip=pymupdf.Rect(x0 * width, y0 * height, x1 * width, y1 * height)
    )
    canvas = pymupdf.open()
    sheet = canvas.new_page(width=pix.width, height=pix.height)
    sheet.insert_image(sheet.rect, pixmap=pix)
    scale_x, scale_y = pix.width / (x1 - x0), pix.height / (y1 - y0)
    for k in range(math.ceil(x0 / step - 1e-9), math.floor(x1 / step + 1e-9) + 1):
        x = (k * step - x0) * scale_x
        sheet.draw_line((x, 0), (x, pix.height), color=(1, 0, 0), width=0.6)
        sheet.insert_text((x + 2, 10), f"{k * step:.3f}".rstrip("0"), fontsize=8, color=(1, 0, 0))
    for k in range(math.ceil(y0 / step - 1e-9), math.floor(y1 / step + 1e-9) + 1):
        y = (k * step - y0) * scale_y
        sheet.draw_line((0, y), (pix.width, y), color=(0, 0, 1), width=0.6)
        sheet.insert_text((2, y - 2), f"{k * step:.3f}".rstrip("0"), fontsize=8, color=(0, 0, 1))
    return sheet.get_pixmap(dpi=72)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("stem", help="drawing PDF stem, e.g. nist_ctc_01_asme1_rd")
    parser.add_argument("--page", type=int, default=1, help="1-based page number")
    parser.add_argument(
        "--region",
        type=float,
        nargs=4,
        default=[0, 0, 1, 1],
        metavar=("X0", "Y0", "X1", "Y1"),
        help="region to render, in page fractions",
    )
    parser.add_argument("--dpi", type=int, default=150)
    parser.add_argument("--step", type=float, default=0.05, help="grid spacing in page fractions")
    parser.add_argument("--out", default=OUT, help="output folder")
    args = parser.parse_args()

    page = open_drawing(args.stem)[args.page - 1]
    region = "" if args.region == [0, 0, 1, 1] else "_" + "_".join(f"{f:g}" for f in args.region)
    path = out_dir(args.out) / f"{args.stem}_p{args.page}_grid{region}.png"
    render_grid(page, args.region, args.dpi, args.step).save(path)
    print(path)


if __name__ == "__main__":
    main()
