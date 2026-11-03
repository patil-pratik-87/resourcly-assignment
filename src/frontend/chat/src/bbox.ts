import type { CSSProperties } from "react";

/** A box as page fractions, [x0, y0, x1, y1] with the origin at the top left. */
export type Bbox = [number, number, number, number];

/** Whether a stored box is usable; a read document may lack one or hold something else. */
export function isBbox(box: unknown): box is Bbox {
  return Array.isArray(box) && box.length === 4 && box.every((n) => typeof n === "number");
}

/** Whether a box is the whole page: what a reader gives a value it read from the whole page. */
export function isWholePage([x0, y0, x1, y1]: Bbox): boolean {
  return x0 <= 0 && y0 <= 0 && x1 >= 1 && y1 >= 1;
}

/** A box placed over its page, as CSS for an element positioned inside the page. */
export function boxStyle([x0, y0, x1, y1]: Bbox): CSSProperties {
  return {
    left: `${x0 * 100}%`,
    top: `${y0 * 100}%`,
    width: `${(x1 - x0) * 100}%`,
    height: `${(y1 - y0) * 100}%`,
  };
}
