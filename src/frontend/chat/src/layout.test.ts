import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it } from "vitest";
import {
  DEFAULT_LAYOUT,
  LAYOUT_KEY,
  MAX_SIDE_SHARE,
  MIN_SIDE_SHARE,
  isListCollapsed,
  loadLayout,
  parseLayout,
  saveLayout,
  sideShareAt,
} from "./layout";
import { fitScaleOf } from "./SheetView";

describe("fitScaleOf", () => {
  const page = { width: 1650, height: 1275 };

  it("fits the width when the viewport is wide relative to the page's shape", () => {
    expect(fitScaleOf(738, 1921, page)).toBeCloseTo((738 - 32) / 1650);
  });

  it("fits the height when the viewport is short", () => {
    expect(fitScaleOf(1500, 400, page)).toBeCloseTo((400 - 32) / 1275);
  });

  it("never goes below the smallest zoom", () => {
    expect(fitScaleOf(10, 10, page)).toBe(0.2);
  });
});

describe("the requests layout", () => {
  beforeEach(() => window.localStorage.clear());

  it("folds the list once a file is open, until the person chooses", () => {
    expect(isListCollapsed(DEFAULT_LAYOUT, false)).toBe(false);
    expect(isListCollapsed(DEFAULT_LAYOUT, true)).toBe(true);
    expect(isListCollapsed({ ...DEFAULT_LAYOUT, listCollapsed: false }, true)).toBe(false);
    expect(isListCollapsed({ ...DEFAULT_LAYOUT, listCollapsed: true }, false)).toBe(true);
  });

  it("gives the side column the share the drag leaves it, within bounds", () => {
    expect(sideShareAt(700, 0, 1000)).toBeCloseTo(0.3);
    expect(sideShareAt(990, 0, 1000)).toBe(MIN_SIDE_SHARE);
    expect(sideShareAt(0, 0, 1000)).toBe(MAX_SIDE_SHARE);
  });

  it("remembers the choices", () => {
    saveLayout({ listCollapsed: false, sideShare: 0.4 });
    expect(loadLayout()).toEqual({ listCollapsed: false, sideShare: 0.4 });
  });

  it("falls back to the default for anything stored that is unusable", () => {
    expect(parseLayout("{nope")).toEqual(DEFAULT_LAYOUT);
    expect(parseLayout(null)).toEqual(DEFAULT_LAYOUT);
    expect(parseLayout('{"listCollapsed":"yes","sideShare":9}')).toEqual({
      listCollapsed: null,
      sideShare: MAX_SIDE_SHARE,
    });
    window.localStorage.setItem(LAYOUT_KEY, "[1]");
    expect(loadLayout()).toEqual(DEFAULT_LAYOUT);
  });
});

describe("the folded list on a narrow screen", () => {
  // jsdom lays nothing out, so hold the stylesheet to its promise: stacked, the list never folds
  // away, since the three grid rows there count on it and nothing could bring it back.
  const css = readFileSync("src/styles.css", "utf8");
  const narrow = css.slice(css.indexOf("@media (max-width: 920px)"));
  const block = narrow.slice(0, narrow.indexOf("@media (max-width: 560px)"));

  it("keeps the request list shown and drops the fold controls", () => {
    expect(block).toMatch(/\.request-list\[hidden\]\s*{\s*display: flex;/);
    expect(block).toMatch(/\.request-list-head \.list-toggle[^{]*{\s*display: none;/);
    expect(block).toMatch(/\.requests\.list-collapsed[^{]*{\s*grid-template-columns: 1fr;/);
  });
});
