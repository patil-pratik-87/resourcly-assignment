import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { AgentApi } from "./api";
import { Decision, ItemGlyph, JustRead } from "./ItemCard";
import { JsonView } from "./JsonView";
import { PhotoAnswerView } from "./PhotoAnswer";
import {
  MAX_SIDE_SHARE,
  MIN_SIDE_SHARE,
  clampSideShare,
  isListCollapsed,
  loadLayout,
  saveLayout,
  sideShareAt,
  type RequestsLayout,
} from "./layout";
import { SheetView } from "./SheetView";
import { TracePanel } from "./TracePanel";
import {
  ROUTE_LABELS,
  elapsed,
  firstItem,
  isActive,
  matchRequest,
  middleCut,
  pageOf,
  plural,
  progressShare,
  sentAt,
  shortId,
  statusLine,
  valuesOnPage,
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

/** Every request and its files; one file open, its page beside its JSON and its trace. */
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
  const collapsed = isListCollapsed(layout, Boolean(record && item));

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
  return {
    routing: "Routing",
    queued: "Queued",
    reading: "Reading",
    answering: "Answering",
    failed: "Failed",
  }[item.status];
}

type Tab = "json" | "answer" | "trace";

/** One item: the page with its values on the left, its routing and its JSON or trace on the right. */
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
  const drawing = item.route?.route === "drawing";
  const title = item.kind === "file" ? item.name : "Your message";
  const [document, setDocument] = useState<ReadDocument | null>(null);
  // The page a person picked; until then a read in progress shows the page it is on.
  const [picked, setPage] = useState<number | null>(null);
  // Until a tab is picked, a drawing opens on its JSON, a photo on its answer once it has one,
  // and anything else on its trace.
  const [pickedTab, setTab] = useState<Tab | null>(null);
  const answer = item.answer;
  const tab = pickedTab ?? (drawing ? "json" : answer ? "answer" : "trace");
  const [hovered, setHovered] = useState<number | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [focusSheet, setFocusSheet] = useState<{ index: number; nonce: number } | null>(null);
  const [focusJson, setFocusJson] = useState<{ index: number; nonce: number } | null>(null);

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

  const livePage = item.status === "reading" ? item.progress?.page : undefined;
  const page = picked ?? livePage ?? 1;

  // What the reader found so far, newest first, gathered from each poll while the screen is open.
  const [found, setFound] = useState<{ step: number; raws: string[] }[]>([]);
  const latest = item.progress?.latest;
  const step = item.progress?.done ?? 0;
  const [seenStep, setSeenStep] = useState(-1);
  if (latest && latest.length > 0 && step !== seenStep) {
    setSeenStep(step);
    setFound((current) => [{ step, raws: latest }, ...current.filter((f) => f.step !== step)]);
  }

  const pages = Math.max(1, document?.page_count ?? item.pages);
  const placed = useMemo(
    () =>
      valuesOnPage(document, page).map(({ index, bbox }) => {
        const value = document?.values?.[index];
        return { index, bbox, title: String(value?.raw ?? value?.id ?? "") };
      }),
    [document, page],
  );

  /** A value chosen on the page: its JSON entry scrolls into view. */
  const selectOnSheet = useCallback((index: number) => {
    setSelected(index);
    setTab("json");
    setFocusJson((current) => ({ index, nonce: (current?.nonce ?? 0) + 1 }));
  }, []);

  /** A value chosen in the JSON: its page opens and its box scrolls into view. */
  const selectInJson = useCallback(
    (index: number) => {
      setSelected(index);
      setPage(pageOf(document, index));
      setFocusSheet((current) => ({ index, nonce: (current?.nonce ?? 0) + 1 }));
    },
    [document],
  );

  // J and K step through the values, Esc clears the selection.
  const count = document?.values?.length ?? 0;
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      if (target?.closest("input, textarea") || event.metaKey || event.ctrlKey || !count) return;
      if (event.key === "Escape") setSelected(null);
      else if (event.key === "j" || event.key === "k") {
        const step = event.key === "j" ? 1 : -1;
        const next = selected === null ? 0 : Math.min(count - 1, Math.max(0, selected + step));
        selectInJson(next);
        setFocusJson((current) => ({ index: next, nonce: (current?.nonce ?? 0) + 1 }));
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [count, selected, selectInJson]);

  // Every uploaded file has pages to show, a photo included; a message without one has none.
  const imageUrl =
    item.kind === "file" && item.pages > 0
      ? api.pageUrl(record.request_id, item.item_id, page)
      : null;
  const live =
    item.status === "reading" && item.progress && item.progress.page === page
      ? { boxes: item.progress.boxes, done: item.progress.page_done }
      : null;
  const version = `${record.status}:${record.items.map((entry) => entry.status).join(",")}`;
  const selectedValue = selected === null ? null : (document?.values?.[selected] ?? null);

  return (
    <>
      <section className="viewer-main" aria-label="Page">
        <div className="viewer-bar">
          <ItemGlyph item={item} />
          <h1 className="viewer-title">{title}</h1>
          <span className="viewer-request" title={record.request_id}>
            Request {shortId(record.request_id)}
          </span>
          {pages > 1 && imageUrl && (
            <div className="pager" role="group" aria-label="Pages">
              <button
                type="button"
                aria-label="Previous page"
                disabled={page <= 1}
                onClick={() => setPage(page - 1)}
              >
                ‹
              </button>
              <span>
                Page {page} of {pages}
              </span>
              <button
                type="button"
                aria-label="Next page"
                disabled={page >= pages}
                onClick={() => setPage(page + 1)}
              >
                ›
              </button>
            </div>
          )}
          {document && (
            <span className="viewer-count">
              {plural(placed.length, "value")} on this page
              <span className="viewer-keys">
                <kbd>J</kbd> <kbd>K</kbd> step
              </span>
            </span>
          )}
          {livePage && picked !== null && picked !== livePage && (
            <button type="button" className="follow" onClick={() => setPage(null)}>
              Follow the read on page {livePage}
            </button>
          )}
        </div>
        {imageUrl ? (
          <SheetView
            imageUrl={imageUrl}
            alt={`Page ${page} of ${item.name}`}
            values={placed}
            live={live}
            hovered={hovered}
            selected={selected}
            focus={focusSheet}
            onHover={setHovered}
            onSelect={selectOnSheet}
          />
        ) : (
          <div className="viewer-message">
            <blockquote>{record.text}</blockquote>
          </div>
        )}
        {selectedValue && (
          <div className="value-card" aria-live="polite">
            <span className="balloon">{(selected ?? 0) + 1}</span>
            <div>
              <div className="value-card-raw">{String(selectedValue.raw ?? "")}</div>
              <div className="value-card-meaning">{String(selectedValue.meaning ?? "")}</div>
            </div>
            <button
              type="button"
              className="value-card-close"
              aria-label="Clear the selection"
              onClick={() => setSelected(null)}
            >
              <svg viewBox="0 0 16 16" aria-hidden>
                <path d="M4 4 L12 12 M12 4 L4 12" />
              </svg>
            </button>
          </div>
        )}
      </section>

      <aside className="viewer-side" aria-label="What the agent did">
        <div
          className="side-resizer"
          role="separator"
          aria-orientation="vertical"
          aria-label="Resize the side column"
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
        <div className="side-summary">
          {item.kind === "text" && record.text && <p className="side-message">{record.text}</p>}
          {item.route ? (
            <Decision route={item.route} />
          ) : (
            <p className="decision pending">{statusLine(item)}</p>
          )}
          {isActive(item) && item.route && (
            <p className="side-status">
              {statusLine(item)}
              {(item.status === "reading" || item.status === "answering") && item.started_at && (
                <span className="read-time">{elapsed(item.started_at)}</span>
              )}
            </p>
          )}
          {item.reply && !answer && (
            <p className="item-reply" role="note">
              {item.reply}
            </p>
          )}
          {item.status === "failed" && <p className="item-error">{item.error}</p>}
          {item.status === "done" && <p className="read-line">{statusLine(item)}</p>}
        </div>
        <div className="side-tabs" role="tablist">
          {drawing && (
            <button
              type="button"
              role="tab"
              aria-selected={tab === "json"}
              onClick={() => setTab("json")}
            >
              JSON
            </button>
          )}
          {answer && (
            <button
              type="button"
              role="tab"
              aria-selected={tab === "answer"}
              onClick={() => setTab("answer")}
            >
              Answer
            </button>
          )}
          <button
            type="button"
            role="tab"
            aria-selected={tab === "trace"}
            onClick={() => setTab("trace")}
          >
            Trace
          </button>
          <span className="spacer" />
          {document && (
            <a className="button" href={api.downloadUrl(record.request_id, item.item_id)} download>
              Download JSON
            </a>
          )}
        </div>
        <div className="side-body">
          {tab === "answer" && answer ? (
            <div className="side-answer">
              <PhotoAnswerView api={api} name={item.name} answer={answer} />
            </div>
          ) : tab === "json" && drawing ? (
            document ? (
              <section aria-label={`JSON of ${title}`}>
                <JsonView
                  document={document}
                  hovered={hovered}
                  selected={selected}
                  focus={focusJson}
                  onHover={setHovered}
                  onSelect={selectInJson}
                />
              </section>
            ) : (
              <div className="side-wait">
                <p>
                  {item.status === "failed"
                    ? "The read failed, so there is no JSON."
                    : "The JSON appears here when the read finishes. What the reader has found so far:"}
                </p>
                {item.status !== "failed" && (
                  <ol className="found">
                    {found.map(({ step: at, raws }, index) => (
                      <li key={at} className={index === 0 ? "newest" : undefined}>
                        <JustRead latest={raws} />
                      </li>
                    ))}
                  </ol>
                )}
              </div>
            )
          ) : (
            <section aria-label="Trace">
              <TracePanel
                api={api}
                requestId={record.request_id}
                itemId={item.item_id}
                version={version}
              />
            </section>
          )}
        </div>
      </aside>
    </>
  );
}
