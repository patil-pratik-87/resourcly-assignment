"""Paint every gold bbox, with its value number, back onto the drawing pages.

Writes one PNG per page that has values. A box that misses its callout, or takes in leader and
extension lines, is easy to see on the result.

    uv run python scripts/gold_tools/overlay.py nist_ctc_01_asme1_rd
"""

import argparse

import pymupdf

from common import OUT, load_gold, open_drawing, out_dir


def render_overlay(page, values, dpi):
    pix = page.get_pixmap(dpi=dpi)
    canvas = pymupdf.open()
    sheet = canvas.new_page(width=pix.width, height=pix.height)
    sheet.insert_image(sheet.rect, pixmap=pix)
    for v in values:
        x0, y0, x1, y1 = v["bbox"]
        box = pymupdf.Rect(x0 * pix.width, y0 * pix.height, x1 * pix.width, y1 * pix.height)
        sheet.draw_rect(box, color=(1, 0, 0), width=1.2)
        sheet.insert_text(
            (box.x0, box.y0 - 2), v["id"].split("-")[1], fontsize=11, color=(0.9, 0, 0)
        )
    return sheet.get_pixmap(dpi=72)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("stem", help="drawing PDF stem, e.g. nist_ctc_01_asme1_rd")
    parser.add_argument("--dpi", type=int, default=150)
    parser.add_argument("--out", default=OUT, help="output folder")
    args = parser.parse_args()

    gold = load_gold(args.stem)
    drawing = open_drawing(args.stem)
    folder = out_dir(args.out)
    for page_number in sorted({v["page"] for v in gold["values"]}):
        values = [v for v in gold["values"] if v["page"] == page_number]
        path = folder / f"{args.stem}_p{page_number}_bbox.png"
        render_overlay(drawing[page_number - 1], values, args.dpi).save(path)
        print(path)


if __name__ == "__main__":
    main()
