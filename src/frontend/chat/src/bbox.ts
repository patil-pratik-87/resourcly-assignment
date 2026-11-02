/** A box as page fractions, [x0, y0, x1, y1] with the origin at the top left. */
export type Bbox = [number, number, number, number];

/** Whether a stored box is usable; a read document may lack one or hold something else. */
export function isBbox(box: unknown): box is Bbox {
  return Array.isArray(box) && box.length === 4 && box.every((n) => typeof n === "number");
}
