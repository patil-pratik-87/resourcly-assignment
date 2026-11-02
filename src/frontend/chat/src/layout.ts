/** How the requests screen shares its width: the request list folds away, the side column resizes. */

export interface RequestsLayout {
  /** Whether the person folded or unfolded the request list; null until they have chosen. */
  listCollapsed: boolean | null;
  /** The side column's share of the screen's width; it holds the JSON and the trace. */
  sideShare: number;
}

export const DEFAULT_SIDE_SHARE = 0.28;
export const MIN_SIDE_SHARE = 0.18;
export const MAX_SIDE_SHARE = 0.55;
export const LAYOUT_KEY = "resourcly.requests.layout";

export const DEFAULT_LAYOUT: RequestsLayout = {
  listCollapsed: null,
  sideShare: DEFAULT_SIDE_SHARE,
};

export function clampSideShare(share: number): number {
  if (!Number.isFinite(share)) return DEFAULT_SIDE_SHARE;
  return Math.min(MAX_SIDE_SHARE, Math.max(MIN_SIDE_SHARE, share));
}

/** The list stays open until a file is open, then folds unless the person chose otherwise. */
export function isListCollapsed(layout: RequestsLayout, fileOpen: boolean): boolean {
  return layout.listCollapsed ?? fileOpen;
}

/** The share a drag to `pointerX` gives the side column of a screen spanning `left` to `right`. */
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
      listCollapsed: typeof found?.listCollapsed === "boolean" ? found.listCollapsed : null,
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
