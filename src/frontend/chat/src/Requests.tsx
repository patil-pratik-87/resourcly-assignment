import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import type { AgentApi } from "./api";
import { Decision, ItemGlyph, ReadProgressView } from "./ItemCard";
import { JsonView } from "./JsonView";
import {
  MAX_SIDE_SHARE,
  MIN_SIDE_SHARE,
  clampSideShare,
  loadLayout,
  saveLayout,
  sideShareAt,
  type RequestsLayout,
} from "./layout";
import { TracePanel } from "./TracePanel";
import {
  ROUTE_LABELS,
  firstItem,
  isActive,
  matchRequest,
  middleCut,
  plural,
  progressShare,
  sentAt,
  shortId,
  statusLine,
} from "./describe";
import type { ReadDocument, RequestItem, RequestRecord } from "./types";

interface Props {
  api: AgentApi;
  requests: RequestRecord[];
  loaded: boolean;
  requestId: string | null;
  itemId: string | null;
  onLookup: (requestId: string) => Promise<RequestRecord>;
  onOpen: (requestId: string, itemId: string, replace?: boolean) => void;
  onChat: () => void;
}

/** Every request and its items; one item open, its result beside the request's trace. */
export function Requests(props: Props) {
  const { api, requests, loaded, requestId, itemId, onLookup, onOpen, onChat } = props;
  // With nothing named in the address, open the newest finished drawing.
  useEffect(() => {
    if (requestId || !loaded) return;
    const first = firstItem(requests);
    if (first) onOpen(first.requestId, first.itemId, true);
  }, [requestId, loaded, requests, onOpen]);

  // A request named in the address that the list does not hold is looked up once.
  const [missing, setMissing] = useState<string | null>(null);
  const record = requests.find((candidate) => candidate.request_id === requestId) ?? null;
  useEffect(() => {
    if (!loaded || !requestId || record) return;
    onLookup(requestId).catch((cause: Error) => setMissing(cause.message));
  }, [loaded, requestId, record, onLookup]);
  const item =
    record?.items.find((candidate) => candidate.item_id === itemId) ?? record?.items[0] ?? null;

  const [layout, setLayout] = useState<RequestsLayout>(loadLayout);
  const screen = useRef<HTMLElement>(null);
  const update = useCallback((next: Partial<RequestsLayout>) => {
    setLayout((current) => {
      const merged = { ...current, ...next };
      saveLayout(merged);
      return merged;
    });
  }, []);
  const collapsed = layout.listCollapsed;

  // A keyboard toggle unmounts or hides the focused button; hand focus to the one that replaces it.
  const toggled = useRef(false);
  const railToggle = useRef<HTMLButtonElement>(null);
  const headToggle = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!toggled.current) return;
    toggled.current = false;
    (collapsed ? railToggle : headToggle).current?.focus();
  }, [collapsed]);
  const fold = (listCollapsed: boolean) => {
    toggled.current = true;
    update({ listCollapsed });
  };

  // The column's floor in pixels can hold it above the share asked for, so report what it has.
  const [shownShare, setShownShare] = useState(layout.sideShare);
  useLayoutEffect(() => {
    function measure() {
      const width = screen.current?.clientWidth;
      const side = screen.current?.querySelector<HTMLElement>(".viewer-side")?.offsetWidth;
      setShownShare(width && side ? side / width : layout.sideShare);
    }
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [layout.sideShare, collapsed, record, item]);

  return (
    <main
      className={`requests${collapsed ? " list-collapsed" : ""}`}
      ref={screen}
      style={{ "--side-share": `${layout.sideShare * 100}%` } as React.CSSProperties}
    >
      {collapsed && (
        <div className="list-rail">
          <button
            type="button"
            ref={railToggle}
            className="list-toggle"
            aria-label="Show the requests"
            aria-expanded={false}
            title="Show the requests"
            onClick={() => fold(false)}
          >
            ›
          </button>
        </div>
      )}
      <nav className="request-list" aria-label="Requests" hidden={collapsed}>
        <div className="request-list-head">
          <h2>Requests</h2>
          <span className="request-list-count">{requests.length}</span>
          <button
            type="button"
            ref={headToggle}
            className="list-toggle"
            aria-label="Hide the requests"
            aria-expanded
            title="Hide the requests"
            onClick={() => fold(true)}
          >
            ‹
          </button>
        </div>
        <Lookup requests={requests} onLookup={onLookup} onOpen={onOpen} />
        {loaded && requests.length === 0 && (
          <div className="request-empty">
            <p>Nothing sent yet.</p>
            <button type="button" className="primary" onClick={onChat}>
              Go to the chat
            </button>
          </div>
        )}
        <ol>
          {requests.map((candidate) => (
            <li key={candidate.request_id} className="request-row">
              <div className="request-row-head">
                <time dateTime={candidate.created_at}>{sentAt(candidate.created_at)}</time>
                <span className="request-row-text">
                  {candidate.text || plural(candidate.items.length, "file")}
                </span>
                <span className="request-row-id">{shortId(candidate.request_id)}</span>
              </div>
              <ul>
                {candidate.items.map((entry) => {
                  const current =
                    candidate.request_id === record?.request_id && entry.item_id === item?.item_id;
                  return (
                    <li key={entry.item_id}>
                      <button
                        type="button"
                        className={`request-item${current ? " current" : ""}`}
                        aria-current={current ? "true" : undefined}
                        onClick={() => onOpen(candidate.request_id, entry.item_id)}
                      >
                        <span className={`route-dot ${entry.route?.route ?? "pending"}`} />
                        <span className="request-item-name" title={entry.name}>
                          {middleCut(entry.kind === "file" ? entry.name : "Your message", 26)}
                        </span>
                        <span className={`request-item-state ${entry.status}`}>
                          {listState(entry)}
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </li>
          ))}
        </ol>
      </nav>
      {record && item ? (
        <ItemViewer
          key={`${record.request_id}/${item.item_id}`}
          api={api}
          record={record}
          item={item}
          sideShare={shownShare}
          screen={screen}
          onSideShare={(share) => update({ sideShare: clampSideShare(share) })}
        />
      ) : (
        <div className="viewer-empty">
          {requestId && missing && <p className="item-error">{missing}</p>}
          {!requestId && loaded && requests.length > 0 && <p>Pick an item on the left.</p>}
        </div>
      )}
    </main>
  );
}

/** Find one request by its id, or the start of it, even one older than the list holds. */
function Lookup({
  requests,
  onLookup,
  onOpen,
}: {
  requests: RequestRecord[];
  onLookup: (requestId: string) => Promise<RequestRecord>;
  onOpen: (requestId: string, itemId: string) => void;
}) {
  const [typed, setTyped] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function find() {
    const id = typed.trim();
    if (!id) return;
    setError(null);
    const matched = matchRequest(id, requests);
    try {
      const found = matched
        ? requests.find((record) => record.request_id === matched)!
        : await onLookup(id);
      const first = found.items[0];
      if (first) onOpen(found.request_id, first.item_id);
    } catch (cause) {
      setError((cause as Error).message);
    }
  }

  return (
    <form
      className="lookup"
      onSubmit={(event) => {
        event.preventDefault();
        void find();
      }}
    >
      <label className="visually-hidden" htmlFor="lookup-id">
        Request id
      </label>
      <input
        id="lookup-id"
        value={typed}
        placeholder="Look up a request id"
        spellCheck={false}
        autoComplete="off"
        onChange={(event) => setTyped(event.target.value)}
      />
      <button type="submit" disabled={!typed.trim()}>
        Open
      </button>
      {error && (
        <p className="lookup-error" role="alert">
          {error}
        </p>
      )}
    </form>
  );
}

function listState(item: RequestItem): string {
  if (item.status === "reading" && item.progress)
    return `${Math.round(progressShare(item.progress) * 100)}%`;
  if (item.status === "done") return plural(item.values ?? 0, "value");
  if (item.status === "answered") return item.route ? ROUTE_LABELS[item.route.route] : "Answered";
  return { routing: "Routing", queued: "Queued", reading: "Reading", failed: "Failed" }[
    item.status
  ];
}

/** One item: its routing and result on the left, the request's trace on the right. */
function ItemViewer({
  api,
  record,
  item,
  sideShare,
  screen,
  onSideShare,
}: {
  api: AgentApi;
  record: RequestRecord;
  item: RequestItem;
  sideShare: number;
  screen: React.RefObject<HTMLElement | null>;
  onSideShare: (share: number) => void;
}) {
  const [document, setDocument] = useState<ReadDocument | null>(null);
  const title = item.kind === "file" ? item.name : "Your message";

  useEffect(() => {
    if (item.status !== "done") return;
    let alive = true;
    api
      .result(record.request_id, item.item_id)
      .then((found) => alive && setDocument(found))
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [api, record.request_id, item.item_id, item.status]);

  const version = `${record.status}:${record.items.map((entry) => entry.status).join(",")}`;

  return (
    <>
      <section className="viewer-main" aria-label="Item">
        <div className="viewer-bar">
          <ItemGlyph item={item} />
          <h1 className="viewer-title">{title}</h1>
          <span className="viewer-request" title={record.request_id}>
            Request {shortId(record.request_id)}
          </span>
          <span className="spacer" />
          {item.status === "done" && (
            <a className="button" href={api.downloadUrl(record.request_id, item.item_id)} download>
              Download JSON
            </a>
          )}
        </div>
        <div className="viewer-body">
          <div className="viewer-summary">
            {item.kind === "text" && record.text && (
              <blockquote className="viewer-message">{record.text}</blockquote>
            )}
            {item.route ? (
              <Decision route={item.route} />
            ) : (
              <p className="decision pending">{statusLine(item)}</p>
            )}
            {isActive(item) && item.route && <ReadProgressView item={item} />}
            {item.reply && (
              <p className="item-reply" role="note">
                {item.reply}
              </p>
            )}
            {item.status === "failed" && <p className="item-error">{item.error}</p>}
            {item.status === "done" && <p className="read-line">{statusLine(item)}</p>}
          </div>
          {document && (
            <section className="viewer-json" aria-label={`JSON of ${title}`}>
              <JsonView document={document} />
            </section>
          )}
        </div>
      </section>

      <aside className="viewer-side" aria-label="Trace">
        <div
          className="side-resizer"
          role="separator"
          aria-orientation="vertical"
          aria-label="Resize the trace column"
          aria-valuemin={Math.round(MIN_SIDE_SHARE * 100)}
          aria-valuemax={Math.round(MAX_SIDE_SHARE * 100)}
          aria-valuenow={Math.round(sideShare * 100)}
          tabIndex={0}
          onPointerDown={(event) => {
            event.preventDefault();
            const bounds = screen.current?.getBoundingClientRect();
            if (!bounds) return;
            const handle = event.currentTarget;
            handle.setPointerCapture?.(event.pointerId);
            const move = (at: PointerEvent) =>
              onSideShare(sideShareAt(at.clientX, bounds.left, bounds.right));
            const stop = () => {
              handle.removeEventListener("pointermove", move);
              handle.removeEventListener("pointerup", stop);
              handle.removeEventListener("pointercancel", stop);
            };
            handle.addEventListener("pointermove", move);
            handle.addEventListener("pointerup", stop);
            handle.addEventListener("pointercancel", stop);
          }}
          onKeyDown={(event) => {
            if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
            event.preventDefault();
            onSideShare(sideShare + (event.key === "ArrowLeft" ? 0.02 : -0.02));
          }}
        />
        <div className="side-head">
          <h2>Trace</h2>
          <span className="muted">what the agent did for request {shortId(record.request_id)}</span>
        </div>
        <div className="side-body">
          <TracePanel
            api={api}
            requestId={record.request_id}
            itemId={item.item_id}
            version={version}
          />
        </div>
      </aside>
    </>
  );
}
