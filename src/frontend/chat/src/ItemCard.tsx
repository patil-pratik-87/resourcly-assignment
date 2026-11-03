import { useEffect, useState } from "react";
import { boxStyle, type Bbox } from "./bbox";
import type { AgentApi } from "./api";
import { FileGlyph } from "./Composer";
import { JsonView } from "./JsonView";
import { AnswerProgress, PhotoAnswerView } from "./PhotoAnswer";
import { AnswerMark, QuestionAnswerView, shownValues } from "./QuestionAnswer";
import {
  ROUTE_LABELS,
  chosenBy,
  percent,
  elapsed,
  fileSize,
  isPhoto,
  plural,
  progressShare,
  readSummary,
  sentence,
  statusLine,
  valuesOnPage,
} from "./describe";
import type { Cited, ReadDocument, RequestItem, Routing } from "./types";

interface Props {
  api: AgentApi;
  requestId: string;
  item: RequestItem;
  onOpen: () => void;
  /** Ask the message's question again about one value, when a tap on a candidate can. */
  onPick?: (cited: Cited) => void;
  /** Make this item what the next message asks about; left out when it cannot be asked about. */
  onAskAbout?: () => void;
}

/** Pages in the chat render small: enough to see the callouts light up, quick to load. */
const CARD_DPI = 96;

/** The agent's answer about one file, or about the text alone: the case, then the result. */
export function ItemCard({ api, requestId, item, onOpen, onPick, onAskAbout }: Props) {
  const [showJson, setShowJson] = useState(false);
  const route = item.route;
  const read = item.values !== null && (item.status === "done" || item.status === "answering");
  const title = item.kind === "file" ? item.name : "Your message";
  const drawing = route?.route === "drawing" && item.kind === "file";
  const picture = item.kind === "file" && !drawing && item.status !== "failed" && item.pages > 0;
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
        <button type="button" className="quiet open" onClick={onOpen}>
          Open in viewer
        </button>
        <StatusPill item={item} />
      </header>

      {route ? (
        <Decision route={route} />
      ) : (
        item.status === "routing" && <p className="decision pending">Choosing the case</p>
      )}

      {drawing && <SheetPreview api={api} requestId={requestId} item={item} onOpen={onOpen} />}
      {picture && (
        <button
          type="button"
          className="item-photo"
          aria-label={`Open ${item.name} in the viewer`}
          onClick={onOpen}
        >
          <img src={api.pageUrl(requestId, item.item_id, 1, CARD_DPI)} alt="" />
        </button>
      )}
      {isPhoto(item) && (item.status === "queued" || item.status === "answering") && (
        <AnswerProgress item={item} />
      )}
      {item.kind === "file" &&
        !isPhoto(item) &&
        (item.status === "reading" || item.status === "queued") && <ReadProgressView item={item} />}
      {item.answer && <PhotoAnswerView api={api} name={item.name} answer={item.answer} />}
      {item.reply && !item.answer && !item.qa && (
        <p className="item-reply" role="note">
          {item.reply}
        </p>
      )}
      {item.status === "failed" && <p className="item-error">{item.error}</p>}
      {read && (
        <div className="item-result">
          <p className="read-line">{readSummary(item)}</p>
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
          {onAskAbout && <AskAbout onAskAbout={onAskAbout} />}
        </div>
      )}
      {!read && onAskAbout && (
        <div className="item-result ask-only">
          <AskAbout onAskAbout={onAskAbout} />
        </div>
      )}
      {read && showJson && (
        <InlineJson api={api} requestId={requestId} itemId={item.item_id} name={title} />
      )}
      {!isPhoto(item) &&
        (item.status === "answering" || (item.kind === "text" && item.status === "queued")) && (
          <AnswerProgress item={item} />
        )}
      {item.qa && (
        <QuestionAnswerView api={api} answer={item.qa} onPick={onPick} withPage={!drawing} />
      )}
    </section>
  );
}

function AskAbout({ onAskAbout }: { onAskAbout: () => void }) {
  return (
    <button type="button" className="ask-about" onClick={onAskAbout}>
      Ask about this
    </button>
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
    answering: "Answering",
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
  const sure = route.confidence === null ? null : percent(route.confidence);
  return (
    <div className="decision">
      <div className="decision-line">
        <span className={`route-tag ${route.route}`}>{ROUTE_LABELS[route.route]}</span>
        {sure !== null && (
          <span className="confidence" title={`Confidence ${route.confidence}`}>
            <span className="confidence-meter" aria-hidden>
              <span style={{ width: `${sure}%` }} />
            </span>
            <span>{sure}% sure</span>
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

/**
 * The drawing's page with its callouts: while reading, the found callouts with the one being read
 * marked; when done, every value the reader placed on the page. When the message's question is
 * answered, the page is the one with the answer's values, which stand out, numbered when they are
 * candidates. A click opens the viewer.
 */
function SheetPreview({ api, requestId, item, onOpen }: Props) {
  const [placed, setPlaced] = useState<{ index: number; bbox: Bbox }[]>([]);
  const progress = item.progress;
  const answered = item.qa
    ? shownValues(item.qa).filter((cited) => cited.item_id === item.item_id && cited.bbox)
    : [];
  const numbered = item.qa?.outcome !== "answer";
  const page = answered[0]?.page ?? progress?.page ?? 1;
  const read = item.values !== null && (item.status === "done" || item.status === "answering");

  useEffect(() => {
    if (!read) return;
    let alive = true;
    api
      .result(requestId, item.item_id)
      .then((document) => alive && setPlaced(valuesOnPage(document, page)))
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [api, requestId, item.item_id, read, page]);

  const boxes =
    item.status === "reading" && progress
      ? progress.boxes.map((bbox, index) => ({
          bbox,
          key: index,
          state:
            index < progress.page_done ? "read" : index === progress.page_done ? "now" : "next",
        }))
      : placed.map(({ bbox, index }) => ({
          bbox,
          key: index,
          state: answered.length ? "dim" : "read",
        }));

  return (
    <button
      type="button"
      className="sheet-preview"
      aria-label={`Open ${item.name} in the viewer`}
      onClick={onOpen}
    >
      <span className="sheet-page">
        <img src={api.pageUrl(requestId, item.item_id, page, CARD_DPI)} alt="" />
        <span className="sheet-marks">
          {boxes.map(({ bbox, key, state }) => (
            <span key={key} className={`mark ${state}`} style={boxStyle(bbox)} />
          ))}
          {answered.map((cited, index) =>
            cited.page === page ? (
              <AnswerMark key={cited.ref} cited={cited} number={numbered ? index + 1 : null} />
            ) : null,
          )}
        </span>
      </span>
      {item.status === "queued" && <span className="sheet-note">Waiting for the reader</span>}
    </button>
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
