import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import type { Bbox } from "./bbox";
import { boxStyle } from "./bbox";

export interface Placed {
  index: number;
  bbox: Bbox;
  /** Shown on hover: what the value says. */
  title: string;
}

interface Props {
  imageUrl: string;
  alt: string;
  values: Placed[];
  /** Callouts a read in progress has found on this page, the first `liveDone` of them read. */
  live?: { boxes: Bbox[]; done: number } | null;
  hovered: number | null;
  selected: number | null;
  /** Bring this value's box into view; `nonce` repeats the request for the same value. */
  focus: { index: number; nonce: number } | null;
  onHover: (index: number | null) => void;
  onSelect: (index: number) => void;
}

const MIN_ZOOM = 0.2;
const MAX_ZOOM = 5;
/** Keep in step with the viewport's padding in styles.css: the grey left around a fitted page. */
const PAGE_MARGIN = 16;

/**
 * The rendered page with a numbered balloon on every value, as on an inspected drawing. The buttons
 * and Ctrl or Cmd and the wheel zoom it; a drag or the scroll bars pan it.
 */
export function SheetView(props: Props) {
  const { imageUrl, alt, values, live, hovered, selected, focus, onHover, onSelect } = props;
  const viewport = useRef<HTMLDivElement>(null);
  const [natural, setNatural] = useState<{ width: number; height: number } | null>(null);
  const [zoom, setZoom] = useState<number | "fit">("fit");
  const [fitScale, setFitScale] = useState(1);
  const scale = zoom === "fit" ? fitScale : zoom;

  const measure = useCallback(() => {
    const box = viewport.current;
    if (!box || !natural) return;
    setFitScale(fitScaleOf(box.clientWidth, box.clientHeight, natural));
  }, [natural]);

  useLayoutEffect(() => {
    measure();
    const box = viewport.current;
    if (!box || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(box);
    return () => observer.disconnect();
  }, [measure]);

  // Ctrl or Cmd and the wheel zoom, as a trackpad pinch does.
  useEffect(() => {
    const box = viewport.current;
    if (!box) return;
    function onWheel(event: WheelEvent) {
      if (!event.ctrlKey && !event.metaKey) return;
      event.preventDefault();
      setZoom((current) => {
        const from = current === "fit" ? fitScale : current;
        return clamp(from * Math.exp(-event.deltaY * 0.01));
      });
    }
    box.addEventListener("wheel", onWheel, { passive: false });
    return () => box.removeEventListener("wheel", onWheel);
  }, [fitScale]);

  useEffect(() => {
    if (!focus) return;
    const box = viewport.current?.querySelector<HTMLElement>(`[data-index="${focus.index}"]`);
    box?.scrollIntoView?.({ block: "center", inline: "center", behavior: "smooth" });
  }, [focus, natural]);

  return (
    <div className="sheet-view">
      <div className="zoom" role="group" aria-label="Zoom">
        <button type="button" aria-label="Zoom out" onClick={() => setZoom(clamp(scale / 1.25))}>
          −
        </button>
        <button
          type="button"
          className="zoom-level"
          title="Fit the page"
          onClick={() => setZoom("fit")}
        >
          {Math.round(scale * 100)}%
        </button>
        <button type="button" aria-label="Zoom in" onClick={() => setZoom(clamp(scale * 1.25))}>
          +
        </button>
      </div>
      <div
        className="sheet-viewport"
        ref={viewport}
        onMouseLeave={() => onHover(null)}
        onPointerDown={(event) => {
          // A drag on the page, off its boxes, pans it as a hand would.
          const box = viewport.current;
          if (!box || event.button !== 0 || (event.target as Element).closest(".vbox")) return;
          const start = { x: event.clientX, y: event.clientY };
          const scroll = { left: box.scrollLeft, top: box.scrollTop };
          box.setPointerCapture?.(event.pointerId);
          box.classList.add("panning");
          const move = (at: PointerEvent) => {
            box.scrollLeft = scroll.left - (at.clientX - start.x);
            box.scrollTop = scroll.top - (at.clientY - start.y);
          };
          const stop = () => {
            box.classList.remove("panning");
            box.removeEventListener("pointermove", move);
            box.removeEventListener("pointerup", stop);
            box.removeEventListener("pointercancel", stop);
          };
          box.addEventListener("pointermove", move);
          box.addEventListener("pointerup", stop);
          box.addEventListener("pointercancel", stop);
        }}
      >
        <div
          className="sheet-paper"
          style={
            natural ? { width: natural.width * scale, height: natural.height * scale } : undefined
          }
        >
          <img
            src={imageUrl}
            alt={alt}
            draggable={false}
            onLoad={(event) =>
              setNatural({
                width: event.currentTarget.naturalWidth,
                height: event.currentTarget.naturalHeight,
              })
            }
          />
          <div className="sheet-overlay">
            {live?.boxes.map((bbox, index) => (
              <span
                key={`live-${index}`}
                className={`mark ${index < live.done ? "read" : index === live.done ? "now" : "next"}`}
                style={boxStyle(bbox)}
              />
            ))}
            {values.map(({ index, bbox, title }) => {
              const state = [
                index === selected ? "selected" : "",
                index === hovered ? "hovered" : "",
              ].join(" ");
              return (
                <button
                  key={index}
                  type="button"
                  data-index={index}
                  className={`vbox ${state}`}
                  style={boxStyle(bbox)}
                  aria-label={`Value ${index + 1}: ${title}`}
                  aria-pressed={index === selected}
                  title={`${index + 1}. ${title}`}
                  onMouseEnter={() => onHover(index)}
                  onFocus={() => onHover(index)}
                  onClick={() => onSelect(index)}
                >
                  <span className="balloon">{index + 1}</span>
                </button>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}

/** The zoom that fits the page in the viewport, a margin kept on every side: width or height binds. */
export function fitScaleOf(
  width: number,
  height: number,
  page: { width: number; height: number },
): number {
  return Math.max(
    MIN_ZOOM,
    Math.min((width - 2 * PAGE_MARGIN) / page.width, (height - 2 * PAGE_MARGIN) / page.height),
  );
}

function clamp(zoom: number): number {
  return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, zoom));
}
