import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it } from "vitest";
import {
  DEFAULT_LAYOUT,
  LAYOUT_KEY,
  MAX_SIDE_SHARE,
  MIN_SIDE_SHARE,
  loadLayout,
  parseLayout,
  saveLayout,
  sideShareAt,
} from "./layout";

describe("the requests layout", () => {
  beforeEach(() => window.localStorage.clear());

  it("gives the trace column the share the drag leaves it, within bounds", () => {
    expect(sideShareAt(700, 0, 1000)).toBeCloseTo(0.3);
    expect(sideShareAt(990, 0, 1000)).toBe(MIN_SIDE_SHARE);
    expect(sideShareAt(0, 0, 1000)).toBe(MAX_SIDE_SHARE);
  });

  it("remembers the choices", () => {
    saveLayout({ listCollapsed: true, sideShare: 0.4 });
    expect(loadLayout()).toEqual({ listCollapsed: true, sideShare: 0.4 });
  });

  it("falls back to the default for anything stored that is unusable", () => {
    expect(parseLayout("{nope")).toEqual(DEFAULT_LAYOUT);
    expect(parseLayout(null)).toEqual(DEFAULT_LAYOUT);
    expect(parseLayout('{"listCollapsed":"yes","sideShare":9}')).toEqual({
      listCollapsed: false,
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
