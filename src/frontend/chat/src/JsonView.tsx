import { type ReactNode, useState } from "react";
import type { ReadDocument } from "./types";

/** Short objects and arrays of plain values print on one line, as a person would write them. */
const INLINE_WIDTH = 64;

/** The document as pretty-printed JSON; each entry of `values` is one numbered block. */
export function JsonView({ document }: { document: ReadDocument }) {
  const [open, setOpen] = useState<Record<string, boolean>>({ features: false });

  const keys = Object.keys(document);
  return (
    <div className="json">
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
                    <div key={index} className="j-entry">
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
