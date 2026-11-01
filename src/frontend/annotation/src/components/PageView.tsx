import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { type Bbox, type Handle, type Point, adjustBbox, bboxFromPixels, isBbox } from "../bbox";
import type { Value } from "../types";

interface Props {
  imageUrl: string;
  values: Value[];
  page: number;
  selected: number | null;
  withIssues: Set<number>;
  editable: boolean;
  onSelect: (index: number | null) => void;
  onBbox: (index: number, bbox: Bbox) => void;
  onDraw: (bbox: Bbox) => void;
}

/**
 * The gesture under way; `result` is the box it would commit, null while it is still a click.
 * A draw that starts on an unselected box selects that box (`pressed`) if it stays a click.
 */
type Drag =
  | { mode: "pan"; start: Point; scroll: Point; moved: boolean; pressed: number | null }
  | { mode: "draw"; start: Point; result: Bbox | null; pressed: number | null }
  | {
      mode: "adjust";
      start: Point;
      index: number;
      handle: Handle;
      bbox: Bbox;
      result: Bbox | null;
    };

const HANDLES: Handle[] = ["nw", "ne", "sw", "se"];
/** Below this many pixels a press is a click, not a drag. */
const DRAG_THRESHOLD = 4;
const MIN_ZOOM = 0.1;
const MAX_ZOOM = 4;

/** The rendered page with a numbered pin per value; drag to draw a box or adjust the selected one. */
export function PageView(props: Props) {
  const { imageUrl, values, page, selected, withIssues, editable, onSelect, onBbox, onDraw } =
    props;
  const viewport = useRef<HTMLDivElement>(null);
  const overlay = useRef<HTMLDivElement>(null);
  const drag = useRef<Drag | null>(null);
  const [natural, setNatural] = useState<{ width: number; height: number } | null>(null);
  const [zoom, setZoom] = useState<number | "fit">("fit");
  const [fitScale, setFitScale] = useState(1);
  const [preview, setPreview] = useState<{ index: number | null; bbox: Bbox } | null>(null);
  const [spaceDown, setSpaceDown] = useState(false);
  const [panning, setPanning] = useState(false);

  const scale = zoom === "fit" ? fitScale : zoom;

  const measureFit = useCallback(() => {
    const box = viewport.current;
    if (!box || !natural) return;
    const margin = parseFloat(getComputedStyle(box).getPropertyValue("--page-margin")) || 0;
    const pad = 2 * margin;
    setFitScale(
      Math.min((box.clientWidth - pad) / natural.width, (box.clientHeight - pad) / natural.height),
    );
  }, [natural]);

  useLayoutEffect(() => {
    measureFit();
    const box = viewport.current;
    if (!box || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measureFit);
    observer.observe(box);
    return () => observer.disconnect();
  }, [measureFit]);

  // Zoom around the cursor with Ctrl or Cmd and the wheel (a trackpad pinch sends the same).
  useEffect(() => {
    const box = viewport.current;
    if (!box) return;
    function onWheel(event: WheelEvent) {
      if (!event.ctrlKey && !event.metaKey) return;
      event.preventDefault();
      zoomBy(Math.exp(-event.deltaY * 0.01), { x: event.clientX, y: event.clientY });
    }
    box.addEventListener("wheel", onWheel, { passive: false });
    return () => box.removeEventListener("wheel", onWheel);
  });

  // Hold Space to pan with the mouse, as in drawing tools. Space still types in a field and
  // presses a button, but a focused pin gives it up, since a click on the page focused it.
  useEffect(() => {
    const typing = (event: KeyboardEvent) =>
      event.target instanceof HTMLElement &&
      event.target.closest("input, textarea, select, button:not(.pin)") !== null;
    const down = (event: KeyboardEvent) => {
      if (event.code === "Space" && !typing(event)) {
        event.preventDefault();
        setSpaceDown(true);
      }
    };
    const up = (event: KeyboardEvent) => event.code === "Space" && setSpaceDown(false);
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
    };
  }, []);

  // Bring a record chosen from the keyboard or the form into view. Not on zoom: zooming keeps
  // the point under the cursor still, and jumping to the selection would undo that.
  useEffect(() => {
    if (selected === null) return;
    const box = overlay.current?.querySelector<HTMLElement>(`[data-index="${selected}"]`);
    const view = viewport.current;
    if (!box || !view) return;
    const b = box.getBoundingClientRect();
    const v = view.getBoundingClientRect();
    if (b.left < v.left || b.right > v.right || b.top < v.top || b.bottom > v.bottom) {
      box.scrollIntoView?.({ block: "center", inline: "center", behavior: "smooth" });
    }
  }, [selected, page]);

  // The page point that must stay under the cursor across a zoom, as page fractions and the
  // screen point it sits at; applied once the page has its new size.
  const zoomAnchor = useRef<{ fraction: Point; screen: Point } | null>(null);

  useLayoutEffect(() => {
    const anchor = zoomAnchor.current;
    const box = viewport.current;
    const page = box?.querySelector<HTMLElement>(".sheet");
    zoomAnchor.current = null;
    if (!anchor || !box || !page) return;
    const rect = page.getBoundingClientRect();
    box.scrollLeft += rect.left + anchor.fraction.x * rect.width - anchor.screen.x;
    box.scrollTop += rect.top + anchor.fraction.y * rect.height - anchor.screen.y;
  }, [scale]);

  function zoomBy(factor: number, around?: Point) {
    const box = viewport.current;
    const page = box?.querySelector<HTMLElement>(".sheet");
    const next = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, scale * factor));
    if (box && page) {
      const view = box.getBoundingClientRect();
      const screen = around ?? { x: view.left + view.width / 2, y: view.top + view.height / 2 };
      const rect = page.getBoundingClientRect();
      zoomAnchor.current = {
        fraction: {
          x: (screen.x - rect.left) / rect.width,
          y: (screen.y - rect.top) / rect.height,
        },
        screen,
      };
    }
    setZoom(next);
  }

  function local(event: React.PointerEvent): Point {
    const rect = overlay.current!.getBoundingClientRect();
    return { x: event.clientX - rect.left, y: event.clientY - rect.top };
  }

  function size() {
    const rect = overlay.current!.getBoundingClientRect();
    return { width: rect.width, height: rect.height };
  }

  function onPointerDown(event: React.PointerEvent) {
    if (event.button === 2) return;
    const target = event.target as HTMLElement;
    const start = local(event);
    if (!editable || spaceDown || event.button === 1) {
      const box = viewport.current!;
      const holder = target.closest<HTMLElement>("[data-index]");
      drag.current = {
        mode: "pan",
        start: { x: event.clientX, y: event.clientY },
        scroll: { x: box.scrollLeft, y: box.scrollTop },
        moved: false,
        pressed: holder ? Number(holder.dataset.index) : null,
      };
      setPanning(true);
    } else {
      const holder = target.closest<HTMLElement>("[data-index]");
      const index = holder ? Number(holder.dataset.index) : null;
      // Only the selected box moves; a drag that starts on any other box draws a new one.
      if (index !== null && index === selected) {
        const handle = (target.dataset.handle as Handle | undefined) ?? "move";
        drag.current = {
          mode: "adjust",
          start,
          index,
          handle,
          bbox: values[index]!.bbox,
          result: null,
        };
      } else {
        drag.current = { mode: "draw", start, result: null, pressed: index };
      }
    }
    overlay.current?.setPointerCapture?.(event.pointerId);
  }

  function onPointerMove(event: React.PointerEvent) {
    const current = drag.current;
    if (!current) return;
    if (current.mode === "pan") {
      const box = viewport.current!;
      const dx = event.clientX - current.start.x;
      const dy = event.clientY - current.start.y;
      if (!current.moved && Math.hypot(dx, dy) < DRAG_THRESHOLD) return;
      current.moved = true;
      box.scrollLeft = current.scroll.x - (event.clientX - current.start.x);
      box.scrollTop = current.scroll.y - (event.clientY - current.start.y);
      return;
    }
    const point = local(event);
    const delta = { x: point.x - current.start.x, y: point.y - current.start.y };
    if (!current.result && Math.hypot(delta.x, delta.y) < DRAG_THRESHOLD) return;
    if (current.mode === "draw") {
      current.result = bboxFromPixels(current.start, point, size());
      setPreview({ index: null, bbox: current.result });
    } else {
      current.result = adjustBbox(current.bbox, current.handle, delta, size());
      setPreview({ index: current.index, bbox: current.result });
    }
  }

  function onPointerUp() {
    const current = drag.current;
    drag.current = null;
    setPanning(false);
    setPreview(null);
    if (!current) return;
    if (current.mode === "pan") {
      // Pointer capture keeps the click from the pin, so a press that did not pan selects here.
      if (!current.moved && current.pressed !== null) onSelect(current.pressed);
      return;
    }
    if (!current.result) {
      // A click: on a box selects it, on the bare page clears the selection.
      onSelect(current.mode === "adjust" ? current.index : current.pressed);
      return;
    }
    if (current.mode === "draw") {
      const [x0, y0, x1, y1] = current.result;
      const { width, height } = size();
      if ((x1 - x0) * width >= DRAG_THRESHOLD && (y1 - y0) * height >= DRAG_THRESHOLD)
        onDraw(current.result);
    } else {
      onBbox(current.index, current.result);
      onSelect(current.index);
    }
  }

  const cursor = panning ? "grabbing" : spaceDown || !editable ? "grab" : "crosshair";

  return (
    <section className="viewer" aria-label="Drawing page">
      <div className="viewer-tools">
        <button
          type="button"
          className="icon"
          onClick={() => zoomBy(1 / 1.25)}
          aria-label="Zoom out"
        >
          −
        </button>
        <button
          type="button"
          className="zoom-level"
          onClick={() => setZoom("fit")}
          title="Fit the page"
        >
          {Math.round(scale * 100)}%
        </button>
        <button type="button" className="icon" onClick={() => zoomBy(1.25)} aria-label="Zoom in">
          +
        </button>
        <button type="button" onClick={() => setZoom("fit")} disabled={zoom === "fit"}>
          Fit
        </button>
        <span className="hint">
          {editable
            ? "Drag on the page to add a value · Space + drag to pan · Ctrl + scroll to zoom"
            : "Drag to pan · Ctrl + scroll to zoom"}
        </span>
      </div>
      <div className="viewport" ref={viewport}>
        <div
          className="sheet"
          style={
            natural ? { width: natural.width * scale, height: natural.height * scale } : undefined
          }
        >
          <img
            src={imageUrl}
            alt={`Page ${page} of the drawing`}
            draggable={false}
            onLoad={(event) =>
              setNatural({
                width: event.currentTarget.naturalWidth,
                height: event.currentTarget.naturalHeight,
              })
            }
          />
          <div
            ref={overlay}
            className="overlay"
            style={{ cursor }}
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            onPointerCancel={() => {
              drag.current = null;
              setPreview(null);
              setPanning(false);
            }}
          >
            {values.map((value, index) => {
              // A value without a usable box has no place on the page until one is drawn.
              if (value.page !== page || !isBbox(value.bbox)) return null;
              const bbox = preview?.index === index ? preview.bbox : value.bbox;
              const isSelected = index === selected;
              const state = withIssues.has(index) ? "issue" : value.status;
              return (
                <div
                  key={index}
                  data-index={index}
                  className={`box ${state}${isSelected ? " selected" : ""}`}
                  style={boxStyle(bbox)}
                >
                  <button
                    type="button"
                    className="pin"
                    aria-label={`Value ${index + 1}: ${value.raw}`}
                    aria-pressed={isSelected}
                    title={`${value.id}${state === "issue" ? " (has issues)" : `: ${value.raw}`}`}
                    onClick={() => onSelect(index)}
                  >
                    {index + 1}
                  </button>
                  {isSelected &&
                    editable &&
                    HANDLES.map((handle) => (
                      <span key={handle} className={`handle ${handle}`} data-handle={handle} />
                    ))}
                </div>
              );
            })}
            {preview?.index === null && (
              <div className="box drawing" style={boxStyle(preview.bbox)} />
            )}
          </div>
        </div>
      </div>
    </section>
  );
}

function boxStyle([x0, y0, x1, y1]: Bbox): React.CSSProperties {
  return {
    left: `${x0 * 100}%`,
    top: `${y0 * 100}%`,
    width: `${(x1 - x0) * 100}%`,
    height: `${(y1 - y0) * 100}%`,
  };
}
