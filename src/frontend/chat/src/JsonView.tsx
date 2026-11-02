import { type ReactNode, useEffect, useRef, useState } from "react";
import type { ReadDocument } from "./types";

interface Props {
  document: ReadDocument;
  hovered?: number | null;
  selected?: number | null;
  /** Scroll this value's entry into view; `nonce` repeats the request for the same value. */
  focus?: { index: number; nonce: number } | null;
  onHover?: (index: number | null) => void;
  /** Without it the entries are plain text, as in the chat; with it each one is a button. */
  onSelect?: (index: number) => void;
}

/** Short objects and arrays of plain values print on one line, as a person would write them. */
const INLINE_WIDTH = 64;

/**
 * The document as pretty-printed JSON. Each entry of `values` is one block, numbered like its
 * balloon on the page, and linked to it both ways when the page is shown beside it.
 */
export function JsonView(props: Props) {
  const { document, hovered = null, selected = null, focus = null, onHover, onSelect } = props;
  const box = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState<Record<string, boolean>>({ features: false });

  useEffect(() => {
    if (!focus) return;
    const entry = box.current?.querySelector<HTMLElement>(`[data-entry="${focus.index}"]`);
    entry?.scrollIntoView?.({ block: "center", behavior: "smooth" });
  }, [focus]);

  const keys = Object.keys(document);
  return (
    <div className="json" ref={box} onMouseLeave={() => onHover?.(null)}>
      <div className="j-line">{"{"}</div>
      <div className="j-children">
        {keys.map((key, position) => {
          const value = document[key];
          const comma = position < keys.length - 1;
          if (key === "values" && Array.isArray(value)) {
            return (
              <div key={key}>
                <div className="j-line">
                  <Key name={key} />
                  {"["}
                  <span className="j-note">{value.length} values</span>
                </div>
                <div className="j-children j-values">
                  {value.map((entry, index) => (
                    <div
                      key={index}
                      data-entry={index}
                      className={`j-entry${onSelect ? " linked" : ""}${
                        index === hovered ? " hovered" : ""
                      }${index === selected ? " selected" : ""}`}
                      {...(onSelect && {
                        role: "button",
                        tabIndex: 0,
                        "aria-label": `JSON of value ${index + 1}`,
                        "aria-pressed": index === selected,
                        onMouseEnter: () => onHover?.(index),
                        onClick: () => onSelect(index),
                        onKeyDown: (event: React.KeyboardEvent) => {
                          if (event.key === "Enter" || event.key === " ") {
                            event.preventDefault();
                            onSelect(index);
                          }
                        },
                      })}
                    >
                      <span className="j-balloon" aria-hidden>
                        {index + 1}
                      </span>
                      <Node value={entry} comma={index < value.length - 1} />
                    </div>
                  ))}
                </div>
                <div className="j-line">
                  {"]"}
                  {comma && ","}
                </div>
              </div>
            );
          }
          if (Array.isArray(value) && value.length > 0 && open[key] === false) {
            return (
              <div key={key} className="j-line">
                <Key name={key} />
                <button
                  type="button"
                  className="j-fold"
                  onClick={() => setOpen((current) => ({ ...current, [key]: true }))}
                >
                  [ {value.length} {key} ]
                </button>
                {comma && ","}
              </div>
            );
          }
          return <Node key={key} name={key} value={value} comma={comma} />;
        })}
      </div>
      <div className="j-line">{"}"}</div>
    </div>
  );
}

function Node({ name, value, comma }: { name?: string; value: unknown; comma: boolean }) {
  const tail = comma ? "," : "";
  const inline = oneLine(value);
  if (inline !== null) {
    return (
      <div className="j-line">
        {name !== undefined && <Key name={name} />}
        {inline}
        {tail}
      </div>
    );
  }
  const array = Array.isArray(value);
  const entries: [string | null, unknown][] = array
    ? (value as unknown[]).map((item) => [null, item])
    : Object.entries(value as Record<string, unknown>);
  return (
    <div>
      <div className="j-line">
        {name !== undefined && <Key name={name} />}
        {array ? "[" : "{"}
      </div>
      <div className="j-children">
        {entries.map(([key, item], index) => (
          <Node
            key={key ?? index}
            name={key ?? undefined}
            value={item}
            comma={index < entries.length - 1}
          />
        ))}
      </div>
      <div className="j-line">
        {array ? "]" : "}"}
        {tail}
      </div>
    </div>
  );
}

function Key({ name }: { name: string }) {
  return (
    <>
      <span className="j-key">"{name}"</span>
      {": "}
    </>
  );
}

/** The value on one line, or null when it is an object or array too long for one. */
function oneLine(value: unknown): ReactNode | null {
  if (value === null || typeof value !== "object") return <Plain value={value} />;
  const parts = Array.isArray(value)
    ? value.map((item) => [null, item] as const)
    : Object.entries(value).map(([key, item]) => [key, item] as const);
  if (parts.some(([, item]) => item !== null && typeof item === "object")) return null;
  const text = JSON.stringify(value);
  if (parts.length > 0 && text.length > INLINE_WIDTH) return null;
  const array = Array.isArray(value);
  return (
    <>
      {array ? "[" : "{"}
      {parts.map(([key, item], index) => (
        <span key={index}>
          {key !== null && <Key name={key} />}
          <Plain value={item} />
          {index < parts.length - 1 && ", "}
        </span>
      ))}
      {array ? "]" : "}"}
    </>
  );
}

function Plain({ value }: { value: unknown }) {
  if (value === null) return <span className="j-null">null</span>;
  if (typeof value === "string") return <span className="j-str">{JSON.stringify(value)}</span>;
  if (typeof value === "number") return <span className="j-num">{value}</span>;
  if (typeof value === "boolean") return <span className="j-bool">{String(value)}</span>;
  return <span>{JSON.stringify(value)}</span>;
}
