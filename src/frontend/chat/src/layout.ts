/** How the requests screen shares its width: the request list folds away, the trace resizes. */

export interface RequestsLayout {
  /** Whether the person folded the request list away. */
  listCollapsed: boolean;
  /** The trace column's share of the screen's width. */
  sideShare: number;
}

export const DEFAULT_SIDE_SHARE = 0.34;
export const MIN_SIDE_SHARE = 0.22;
export const MAX_SIDE_SHARE = 0.6;
export const LAYOUT_KEY = "resourcly.requests.layout";

export const DEFAULT_LAYOUT: RequestsLayout = {
  listCollapsed: false,
  sideShare: DEFAULT_SIDE_SHARE,
};

export function clampSideShare(share: number): number {
  if (!Number.isFinite(share)) return DEFAULT_SIDE_SHARE;
  return Math.min(MAX_SIDE_SHARE, Math.max(MIN_SIDE_SHARE, share));
}

/** The share a drag to `pointerX` gives the trace column of a screen spanning `left` to `right`. */
export function sideShareAt(pointerX: number, left: number, right: number): number {
  const width = right - left;
  if (width <= 0) return DEFAULT_SIDE_SHARE;
  return clampSideShare((right - pointerX) / width);
}

export function parseLayout(raw: string | null): RequestsLayout {
  if (!raw) return DEFAULT_LAYOUT;
  try {
    const found = JSON.parse(raw) as Partial<RequestsLayout> | null;
    return {
      listCollapsed: found?.listCollapsed === true,
      sideShare:
        typeof found?.sideShare === "number" ? clampSideShare(found.sideShare) : DEFAULT_SIDE_SHARE,
    };
  } catch {
    return DEFAULT_LAYOUT;
  }
}

export function loadLayout(): RequestsLayout {
  try {
    return parseLayout(window.localStorage.getItem(LAYOUT_KEY));
  } catch {
    return DEFAULT_LAYOUT;
  }
}

export function saveLayout(layout: RequestsLayout): void {
  try {
    window.localStorage.setItem(LAYOUT_KEY, JSON.stringify(layout));
  } catch {
    // Storage can be blocked; the layout then lasts for this visit only.
  }
}
