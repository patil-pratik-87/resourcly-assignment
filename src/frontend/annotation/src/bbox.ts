/** A box as page fractions, [x0, y0, x1, y1] with the origin at the top left. */
export type Bbox = [number, number, number, number];

/** Whether a stored box is usable; a gold file may lack one or hold something else. */
export function isBbox(box: unknown): box is Bbox {
  return Array.isArray(box) && box.length === 4 && box.every((n) => typeof n === "number");
}

export interface Size {
  width: number;
  height: number;
}

export interface PixelBox {
  left: number;
  top: number;
  width: number;
  height: number;
}

export function bboxToPixels([x0, y0, x1, y1]: Bbox, size: Size): PixelBox {
  return {
    left: x0 * size.width,
    top: y0 * size.height,
    width: (x1 - x0) * size.width,
    height: (y1 - y0) * size.height,
  };
}

export interface Point {
  x: number;
  y: number;
}

export function bboxFromPixels(a: Point, b: Point, size: Size): Bbox {
  const x = (px: number) => round(clamp(px / size.width));
  const y = (px: number) => round(clamp(px / size.height));
  return [
    x(Math.min(a.x, b.x)),
    y(Math.min(a.y, b.y)),
    x(Math.max(a.x, b.x)),
    y(Math.max(a.y, b.y)),
  ];
}

/** "move" drags the whole box; a compass corner drags that corner. */
export type Handle = "move" | "nw" | "ne" | "sw" | "se";

export function adjustBbox(bbox: Bbox, handle: Handle, delta: Point, size: Size): Bbox {
  const [x0, y0, x1, y1] = bbox;
  if (handle === "move") {
    const dx = Math.min(1 - x1, Math.max(-x0, delta.x / size.width));
    const dy = Math.min(1 - y1, Math.max(-y0, delta.y / size.height));
    return [x0 + dx, y0 + dy, x1 + dx, y1 + dy].map(round) as Bbox;
  }
  const box = bboxToPixels(bbox, size);
  const left = box.left + (handle.includes("w") ? delta.x : 0);
  const right = box.left + box.width + (handle.includes("e") ? delta.x : 0);
  const top = box.top + (handle.includes("n") ? delta.y : 0);
  const bottom = box.top + box.height + (handle.includes("s") ? delta.y : 0);
  return bboxFromPixels({ x: left, y: top }, { x: right, y: bottom }, size);
}

function clamp(fraction: number): number {
  return Math.min(1, Math.max(0, fraction));
}

/** Gold files store fractions with three decimals, about 1.6 px on a 150 dpi page. */
function round(fraction: number): number {
  return Math.round(fraction * 1000) / 1000;
}
