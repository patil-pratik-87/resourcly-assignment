import { describe, expect, it } from "vitest";
import { adjustBbox, bboxFromPixels, bboxToPixels } from "./bbox";

const page = { width: 1650, height: 1275 };

describe("bboxToPixels", () => {
  it("maps page fractions to a pixel box on the rendered page", () => {
    // CTC-01 value ctc01-07 on a 1650 x 1275 render (11 x 8.5 in at 150 dpi).
    expect(bboxToPixels([0.737, 0.428, 0.789, 0.473], page)).toEqual({
      left: expect.closeTo(1216.05),
      top: expect.closeTo(545.7),
      width: expect.closeTo(85.8),
      height: expect.closeTo(57.375),
    });
  });
});

describe("bboxFromPixels", () => {
  it("turns a drag between two pixel points back into page fractions", () => {
    expect(bboxFromPixels({ x: 1216.05, y: 545.7 }, { x: 1301.85, y: 603.075 }, page)).toEqual([
      0.737, 0.428, 0.789, 0.473,
    ]);
  });

  it("orders the corners whichever way the drag went", () => {
    expect(bboxFromPixels({ x: 330, y: 255 }, { x: 165, y: 127.5 }, page)).toEqual([
      0.1, 0.1, 0.2, 0.2,
    ]);
  });

  it("clamps a drag that leaves the page to its edges", () => {
    expect(bboxFromPixels({ x: -40, y: 1200 }, { x: 1700, y: 1300 }, page)).toEqual([
      0, 0.941, 1, 1,
    ]);
  });
});

describe("adjustBbox", () => {
  it("moves the whole box by a pixel drag", () => {
    expect(adjustBbox([0.1, 0.1, 0.2, 0.2], "move", { x: 165, y: -127.5 }, page)).toEqual([
      0.2, 0, 0.3, 0.1,
    ]);
  });

  it("keeps a moved box whole and on the page", () => {
    expect(adjustBbox([0.1, 0.8, 0.2, 0.9], "move", { x: -330, y: 255 }, page)).toEqual([
      0, 0.9, 0.1, 1,
    ]);
  });

  it("resizes from the corner that was dragged", () => {
    expect(adjustBbox([0.1, 0.1, 0.2, 0.2], "se", { x: 165, y: 127.5 }, page)).toEqual([
      0.1, 0.1, 0.3, 0.3,
    ]);
    expect(adjustBbox([0.1, 0.1, 0.2, 0.2], "nw", { x: -165, y: 0 }, page)).toEqual([
      0, 0.1, 0.2, 0.2,
    ]);
  });

  it("flips a corner dragged past the opposite edge instead of inverting the box", () => {
    expect(adjustBbox([0.1, 0.1, 0.2, 0.2], "ne", { x: -330, y: 0 }, page)).toEqual([
      0, 0.1, 0.1, 0.2,
    ]);
  });
});
