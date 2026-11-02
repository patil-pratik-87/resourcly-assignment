import { useEffect, useState } from "react";
import type { AgentApi } from "./api";
import { FileGlyph } from "./Composer";
import { JsonView } from "./JsonView";
import {
  ROUTE_LABELS,
  chosenBy,
  elapsed,
  fileSize,
  plural,
  progressShare,
  sentence,
  statusLine,
} from "./describe";
import type { ReadDocument, RequestItem, Routing } from "./types";

interface Props {
  api: AgentApi;
  requestId: string;
  item: RequestItem;
  onOpen: () => void;
}

/** The agent's answer about one file, or about the text alone: the case, then the result. */
export function ItemCard({ api, requestId, item, onOpen }: Props) {
  const [showJson, setShowJson] = useState(false);
  const route = item.route;
  const read = item.status === "done";
  const title = item.kind === "file" ? item.name : "Your message";
  return (
    <section className={`item-card is-${item.status}`} aria-label={title}>
      <header className="item-head">
        <ItemGlyph item={item} />
        <div className="item-title">
          <strong>{title}</strong>
          {item.kind === "file" && item.size > 0 && (
            <span className="item-facts">
              {item.pages > 1 && <span>{plural(item.pages, "page")}</span>}
              <span>{fileSize(item.size)}</span>
            </span>
          )}
        </div>
        <StatusPill item={item} />
      </header>

      {route ? (
        <Decision route={route} />
      ) : (
        item.status === "routing" && <p className="decision pending">Choosing the case</p>
      )}

      {(item.status === "reading" || item.status === "queued") && <ReadProgressView item={item} />}
      {item.reply && (
        <p className="item-reply" role="note">
          {item.reply}
        </p>
      )}
      {item.status === "failed" && <p className="item-error">{item.error}</p>}
      {read && <p className="read-line">{statusLine(item)}</p>}

      <div className="item-actions">
        {read && (
          <>
            <button
              type="button"
              aria-expanded={showJson}
              onClick={() => setShowJson((shown) => !shown)}
            >
              {showJson ? "Hide JSON" : "Show JSON"}
            </button>
            <a className="button" href={api.downloadUrl(requestId, item.item_id)} download>
              Download JSON
            </a>
          </>
        )}
        <button type="button" className="quiet" onClick={onOpen}>
          Open in requests
        </button>
      </div>
      {read && showJson && (
        <InlineJson api={api} requestId={requestId} itemId={item.item_id} name={title} />
      )}
    </section>
  );
}

export function ItemGlyph({ item }: { item: RequestItem }) {
  return item.kind === "file" ? (
    <FileGlyph type={item.media_type} name={item.name} />
  ) : (
    <span className="file-glyph text" aria-hidden>
      TXT
    </span>
  );
}

function StatusPill({ item }: { item: RequestItem }) {
  const label = {
    routing: "Routing",
    queued: "Queued",
    reading: "Reading",
    done: "Done",
    answered: "Answered",
    failed: "Failed",
  }[item.status];
  return (
    <span className={`status-pill ${item.status}`} role="status">
      {label}
    </span>
  );
}

/** The router's answer for an item: the case, the layer that chose it, how sure, and why. */
export function Decision({ route }: { route: Routing }) {
  const percent = route.confidence === null ? null : Math.round(route.confidence * 100);
  return (
    <div className="decision">
      <div className="decision-line">
        <span className={`route-tag ${route.route}`}>{ROUTE_LABELS[route.route]}</span>
        {percent !== null && (
          <span className="confidence" title={`Confidence ${route.confidence}`}>
            <span className="confidence-meter" aria-hidden>
              <span style={{ width: `${percent}%` }} />
            </span>
            <span>{percent}% sure</span>
          </span>
        )}
      </div>
      <p className="decision-why">
        <span className="decision-layer">{chosenBy(route.layer)}</span> {sentence(route.reason)}
      </p>
    </div>
  );
}

/** How far a drawing's read has got, and the text the reader found last. */
export function ReadProgressView({ item }: { item: RequestItem }) {
  const progress = item.progress;
  const share = progressShare(progress);
  return (
    <div className="read-progress">
      <div
        className="read-bar"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(share * 100)}
        aria-label={`Reading ${item.name}`}
      >
        <span style={{ width: `${share * 100}%` }} />
      </div>
      <div className="read-line">
        <span>{statusLine(item)}</span>
        {item.status === "reading" && item.started_at && (
          <span className="read-time">{elapsed(item.started_at)}</span>
        )}
      </div>
      {progress?.latest.length ? <JustRead latest={progress.latest} /> : null}
    </div>
  );
}

/** The text the reader found in the callout it read last. */
export function JustRead({ latest }: { latest: string[] }) {
  return (
    <div className="just-read">
      <span>Just read</span>
      {latest.map((raw, index) => (
        <code key={index}>{raw}</code>
      ))}
    </div>
  );
}

/** A read drawing's JSON in the chat, fetched when first shown. */
function InlineJson({
  api,
  requestId,
  itemId,
  name,
}: {
  api: AgentApi;
  requestId: string;
  itemId: string;
  name: string;
}) {
  const [document, setDocument] = useState<ReadDocument | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    api
      .result(requestId, itemId)
      .then((found) => alive && setDocument(found))
      .catch((cause: Error) => alive && setError(cause.message));
    return () => {
      alive = false;
    };
  }, [api, requestId, itemId]);

  return (
    <section className="inline-json" aria-label={`JSON of ${name}`}>
      {document ? (
        <JsonView document={document} />
      ) : (
        <p className="muted">{error ? `Could not load the JSON: ${error}` : "Loading the JSON"}</p>
      )}
    </section>
  );
}
