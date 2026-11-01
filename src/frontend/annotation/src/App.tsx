import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
} from "react";
import { type Api, createApi } from "./api";
import { type Bbox, isBbox } from "./bbox";
import { DOCUMENT_FIELDS, TITLE_BLOCK_FIELDS } from "./schema";
import { FeaturesPanel } from "./components/FeaturesPanel";
import { PageView } from "./components/PageView";
import { RecordDetails } from "./components/RecordDetails";
import { RecordForm } from "./components/RecordForm";
import { TitleBlockPanel } from "./components/TitleBlockPanel";
import { addFeature, addValue, deleteValue, withDefaults } from "./document";
import { type EditorState, editorReducer, isDirty, openEditor } from "./editor";
import { applyField } from "./form";
import { issuesUnder, messagesByField, valuesWithIssues } from "./issues";
import type { DrawingSummary, GoldDocument, Issue } from "./types";

const browserApi = createApi((url, init) => window.fetch(url, init));

/** Wait this long after the last edit before asking the API to check the document. */
const CHECK_DELAY_MS = 400;

export default function App({ api = browserApi }: { api?: Api }) {
  const [drawings, setDrawings] = useState<DrawingSummary[]>([]);
  const [editor, setEditor] = useState<EditorState | null>(null);
  const [demo, setDemo] = useState(() => new URLSearchParams(window.location.search).has("demo"));
  const [error, setError] = useState<string | null>(null);

  const refreshDrawings = useCallback(() => api.drawings().then(setDrawings), [api]);

  const open = useCallback(
    async (drawing: string) => {
      try {
        setEditor(openEditor(drawing, withDefaults(await api.document(drawing))));
        setError(null);
        window.history.replaceState(
          null,
          "",
          `${window.location.search}#${encodeURIComponent(drawing)}`,
        );
      } catch (cause) {
        setError(`Could not open ${drawing}: ${(cause as Error).message}`);
      }
    },
    [api],
  );

  useEffect(() => {
    api
      .drawings()
      .then((list) => {
        setDrawings(list);
        const wanted = drawingInHash();
        const first =
          list.find((row) => row.drawing === wanted) ?? list.find((row) => row.has_gold) ?? list[0];
        if (first) return open(first.drawing);
        setError("No drawings found. Check RESOURCLY_DRAWINGS_DIR and RESOURCLY_GOLD_DIR.");
      })
      .catch((cause: Error) => setError(`Could not reach the API: ${cause.message}`));
  }, [api, open]);

  if (!editor) {
    return (
      <main className="loading">
        <p>{error ?? "Loading drawings…"}</p>
        {/* If the first drawing would not open, another can still be picked. */}
        {error && drawings.length > 0 && (
          <label className="picker">
            Drawing
            <select name="drawing" value="" onChange={(event) => void open(event.target.value)}>
              <option value="" disabled>
                Pick a drawing
              </option>
              {drawings.map((row) => (
                <option key={row.drawing} value={row.drawing}>
                  {row.drawing}
                </option>
              ))}
            </select>
          </label>
        )}
      </main>
    );
  }
  return (
    <Editor
      key={editor.drawing}
      api={api}
      initial={editor}
      drawings={drawings}
      demo={demo}
      onDemo={setDemo}
      onOpen={open}
      onSaved={refreshDrawings}
      error={error}
    />
  );
}

type Tab = "value" | "features" | "title";

interface EditorProps {
  api: Api;
  initial: EditorState;
  drawings: DrawingSummary[];
  demo: boolean;
  error: string | null;
  onDemo: (demo: boolean) => void;
  onOpen: (drawing: string) => void;
  onSaved: () => void;
}

function Editor({ api, initial, drawings, demo, error, onDemo, onOpen, onSaved }: EditorProps) {
  const [state, dispatch] = useReducer(editorReducer, initial);
  const [tab, setTab] = useState<Tab>("value");
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const { drawing, document, selected, page, issues } = state;
  const dirty = isDirty(state);
  const value = selected === null ? null : (document.values[selected] ?? null);
  const withIssues = useMemo(() => valuesWithIssues(issues), [issues]);
  const approved = document.values.filter((item) => item.status === "approved").length;
  const imageUrl = useMemo(() => api.pageImage(drawing, page), [api, drawing, page]);

  // Ask the API to check every version of the document, shortly after the last edit.
  useEffect(() => {
    const sent = document;
    const timer = setTimeout(() => {
      api
        .check(drawing, sent)
        .then((found) => dispatch({ type: "issues", issues: found, document: sent }))
        .catch(() => {});
    }, CHECK_DELAY_MS);
    return () => clearTimeout(timer);
  }, [api, drawing, document]);

  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  // The latest state, for the save and approve callbacks; set after each render commits.
  const latest = useRef(state);
  useLayoutEffect(() => {
    latest.current = state;
  });

  // One save at a time: a second Cmd+S while a PUT is in flight would race it.
  const inFlight = useRef(false);
  const save = useCallback(async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    const sent = latest.current.document;
    setSaving(true);
    try {
      const result = await api.save(drawing, sent);
      if (result.ok) {
        dispatch({ type: "saved", sent, stored: result.document });
        setNotice({ kind: "ok", text: "Saved" });
        onSaved();
      } else {
        dispatch({ type: "issues", issues: result.issues, document: sent });
        const count = result.issues.length;
        setNotice({
          kind: "error",
          text: `Not saved: ${count} ${count === 1 ? "issue" : "issues"}`,
        });
      }
    } catch (cause) {
      setNotice({ kind: "error", text: `Not saved: ${(cause as Error).message}` });
    } finally {
      inFlight.current = false;
      setSaving(false);
    }
  }, [api, drawing, onSaved]);

  const approve = useCallback(() => {
    const { document: current, selected: index } = latest.current;
    const record = index === null ? undefined : current.values[index];
    if (index === null || !record) return;
    const status = record.status === "approved" ? "draft" : "approved";
    dispatch({ type: "editValue", index, value: applyField(record, "status", status) });
    if (status === "approved") dispatch({ type: "step", by: 1 });
  }, []);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key === "s") {
        event.preventDefault();
        if (!demo) void save();
        return;
      }
      if (isTyping(event.target) || event.metaKey || event.ctrlKey || event.altKey) return;
      if (event.key === "j") dispatch({ type: "step", by: 1 });
      else if (event.key === "k") dispatch({ type: "step", by: -1 });
      else if (event.key === "Escape") dispatch({ type: "select", index: null });
      else if (event.key === "a" && !demo) approve();
      else return;
      // A focused select would otherwise also jump to the option starting with that letter.
      event.preventDefault();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [approve, demo, save]);

  // A failed save's message describes the document as it was; an edit makes it stale.
  const [noticeDocument, setNoticeDocument] = useState(document);
  if (noticeDocument !== document) {
    setNoticeDocument(document);
    if (notice?.kind === "error") setNotice(null);
  }

  useEffect(() => {
    if (!notice || notice.kind !== "ok") return;
    const timer = setTimeout(() => setNotice(null), 2500);
    return () => clearTimeout(timer);
  }, [notice]);

  function switchDrawing(next: string) {
    if (next === drawing) return;
    if (dirty && !window.confirm(`Discard the unsaved changes to ${drawing}?`)) return;
    onOpen(next);
  }

  function addValueAt(bbox: Bbox) {
    // A selected value with no box takes the drawn one; otherwise drawing adds a value.
    if (value && selected !== null && !isBbox(value.bbox)) {
      dispatch({ type: "editValue", index: selected, value: { ...value, bbox, page } });
      return;
    }
    const added = addValue(document, page, bbox);
    dispatch({ type: "replace", document: added.document, select: added.index });
    setTab("value");
  }

  function removeSelected() {
    if (selected === null || !value) return;
    if (!window.confirm(`Delete ${value.id} (${value.raw || "empty"})?`)) return;
    const next = deleteValue(document, selected);
    dispatch({
      type: "replace",
      document: next,
      select: next.values.length === 0 ? null : Math.min(selected, next.values.length - 1),
    });
  }

  // The banner shows what no panel has a field for: document-level issues and title block keys
  // outside the schema. Value and feature issues show in their own panels.
  const documentIssues = issues.filter(
    (issue) =>
      (issue.loc[0] !== "values" &&
        issue.loc[0] !== "features" &&
        issue.loc[0] !== "title_block") ||
      (issue.loc[0] === "title_block" && !TITLE_BLOCK_FIELDS.includes(String(issue.loc[1]))),
  );
  const featureIssues = issuesUnder(issues, "features").length;
  const titleIssues = issuesUnder(issues, "title_block").length;

  return (
    <div className={`app${demo ? " demo" : ""}`}>
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark" aria-hidden />
          Gold labels
        </div>
        <label className="picker">
          <span className="visually-hidden">Drawing</span>
          <select
            name="drawing"
            value={drawing}
            onChange={(event) => switchDrawing(event.target.value)}
          >
            {drawings.map((row) => (
              <option key={row.drawing} value={row.drawing}>
                {row.drawing}
                {row.has_gold
                  ? `  ·  ${row.approved}/${row.values} approved`
                  : "  ·  no labels yet"}
              </option>
            ))}
          </select>
        </label>
        <div className="counts" aria-label="Counts">
          <span>
            <strong>{document.values.length}</strong>{" "}
            {document.values.length === 1 ? "value" : "values"}
          </span>
          <span>
            <strong>{approved}</strong> approved
          </span>
          {issues.length > 0 && (
            <button
              type="button"
              className="issue-count"
              onClick={() => {
                const first = issues.find((issue) => issue.loc[0] === "values");
                if (first) {
                  dispatch({ type: "select", index: first.loc[1] as number });
                  setTab("value");
                } else if (featureIssues) setTab("features");
                else if (titleIssues) setTab("title");
              }}
            >
              <strong>{issues.length}</strong> {issues.length === 1 ? "issue" : "issues"}
            </button>
          )}
        </div>
        {document.page_count > 1 && (
          <nav className="pager" aria-label="Pages">
            <button
              type="button"
              className="icon"
              aria-label="Previous page"
              disabled={page <= 1}
              onClick={() => dispatch({ type: "page", page: page - 1 })}
            >
              ‹
            </button>
            <span>
              {`Page ${page} of ${document.page_count}`}
              {/* page_coverage lists the pages labelled in full; the others hold no gold. */}
              {document.page_coverage && !document.page_coverage.includes(page) && (
                <span className="muted"> (not labelled)</span>
              )}
            </span>
            <button
              type="button"
              className="icon"
              aria-label="Next page"
              disabled={page >= document.page_count}
              onClick={() => dispatch({ type: "page", page: page + 1 })}
            >
              ›
            </button>
          </nav>
        )}
        <div className="spacer" />
        <label className="switch">
          <input
            type="checkbox"
            name="demo"
            checked={demo}
            onChange={(event) => onDemo(event.target.checked)}
          />
          <span aria-hidden className="switch-track" />
          Demo
        </label>
      </header>

      {(error || documentIssues.length > 0) && (
        <div className="banner" role="alert">
          {error ??
            documentIssues.map((issue, i) => {
              const path = issue.loc.join(".");
              const unknown = unknownKey(document, issue.loc);
              return (
                <span key={i} className="banner-item">
                  {path ? `${path}: ` : ""}
                  {issue.message}
                  {unknown && (
                    <button
                      type="button"
                      className="link"
                      onClick={() =>
                        dispatch({ type: "replace", document: withoutKey(document, issue.loc) })
                      }
                    >
                      Remove {path}
                    </button>
                  )}
                </span>
              );
            })}
        </div>
      )}

      <main className="workspace">
        <PageView
          imageUrl={imageUrl}
          values={document.values}
          page={page}
          selected={selected}
          withIssues={withIssues}
          editable={!demo}
          onSelect={(index) => dispatch({ type: "select", index })}
          onBbox={(index, bbox) =>
            dispatch({ type: "editValue", index, value: { ...document.values[index]!, bbox } })
          }
          onDraw={addValueAt}
        />

        <aside className="side">
          <div className="side-head">
            <div className="tabs" role="tablist">
              <TabButton tab="value" current={tab} onSelect={setTab}>
                Value
              </TabButton>
              <TabButton tab="features" current={tab} onSelect={setTab} issues={featureIssues}>
                Features <span className="muted">{document.features.length}</span>
              </TabButton>
              <TabButton tab="title" current={tab} onSelect={setTab} issues={titleIssues}>
                Title block
              </TabButton>
            </div>
            {!demo && (
              <div className="actions">
                <button type="button" onClick={() => addValueAt([0.45, 0.45, 0.55, 0.5])}>
                  Add value
                </button>
                <button
                  type="button"
                  onClick={() => {
                    dispatch({ type: "replace", document: addFeature(document, page).document });
                    setTab("features");
                  }}
                >
                  Add feature
                </button>
                <div className="spacer" />
                <span className={`save-state${notice ? ` ${notice.kind}` : ""}`} role="status">
                  {notice?.text ?? (dirty ? "Unsaved changes" : "")}
                </span>
                <button
                  type="button"
                  className="primary"
                  disabled={saving}
                  onClick={() => void save()}
                >
                  {saving ? "Saving…" : "Save"}
                </button>
              </div>
            )}
          </div>

          <div className="side-body">
            {tab === "value" &&
              (value && selected !== null ? (
                <>
                  <div className="record-head">
                    <button
                      type="button"
                      className="icon"
                      aria-label="Previous value"
                      disabled={selected === 0}
                      onClick={() => dispatch({ type: "step", by: -1 })}
                    >
                      ‹
                    </button>
                    <span className="record-title">
                      Value {selected + 1}{" "}
                      <span className="muted">of {document.values.length}</span>
                    </span>
                    <button
                      type="button"
                      className="icon"
                      aria-label="Next value"
                      disabled={selected === document.values.length - 1}
                      onClick={() => dispatch({ type: "step", by: 1 })}
                    >
                      ›
                    </button>
                    <span className={`chip ${withIssues.has(selected) ? "issue" : value.status}`}>
                      {withIssues.has(selected) ? "has issues" : value.status}
                    </span>
                  </div>
                  {demo ? (
                    <RecordDetails document={document} value={value} />
                  ) : (
                    <RecordForm
                      document={document}
                      value={value}
                      issues={messagesByField(issues, "values", selected)}
                      onChange={(next) =>
                        dispatch({ type: "editValue", index: selected, value: next })
                      }
                    />
                  )}
                  {!demo && (
                    <div className="record-actions">
                      <button
                        type="button"
                        className={value.status === "approved" ? "" : "approve"}
                        onClick={approve}
                      >
                        {value.status === "approved" ? "Mark as draft" : "Approve"}
                      </button>
                      <button type="button" className="danger" onClick={removeSelected}>
                        Delete
                      </button>
                    </div>
                  )}
                </>
              ) : (
                <ValueList
                  state={state}
                  withIssues={withIssues}
                  demo={demo}
                  onSelect={(index) => dispatch({ type: "select", index })}
                />
              ))}
            {tab === "features" && (
              <FeaturesPanel
                document={document}
                issues={issues}
                readOnly={demo}
                onChange={(next) => dispatch({ type: "replace", document: next })}
              />
            )}
            {tab === "title" && (
              <TitleBlockPanel
                document={document}
                issues={issues}
                readOnly={demo}
                onChange={(next) => dispatch({ type: "replace", document: next })}
              />
            )}
          </div>

          <footer className="shortcuts">
            <kbd>J</kbd> <kbd>K</kbd> next, previous
            {!demo && (
              <>
                {" · "}
                <kbd>A</kbd> approve · <kbd>⌘S</kbd> save
              </>
            )}
            {" · "}
            <kbd>Esc</kbd> deselect
          </footer>
        </aside>
      </main>
    </div>
  );
}

function TabButton({
  tab,
  current,
  issues = 0,
  onSelect,
  children,
}: {
  tab: Tab;
  current: Tab;
  issues?: number;
  onSelect: (tab: Tab) => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={tab === current}
      className="tab"
      onClick={() => onSelect(tab)}
    >
      {children}
      {issues > 0 && <span className="dot" aria-label={`${issues} issues`} />}
    </button>
  );
}

function ValueList({
  state,
  withIssues,
  demo,
  onSelect,
}: {
  state: EditorState;
  withIssues: Set<number>;
  demo: boolean;
  onSelect: (index: number) => void;
}) {
  const { values } = state.document;
  if (values.length === 0) {
    return (
      <p className="empty">
        No values on this drawing yet.
        {!demo && " Drag a box around a callout on the page, or press Add value."}
      </p>
    );
  }
  return (
    <ol className="value-list">
      {values.map((value, index) => (
        <li key={index}>
          <button type="button" onClick={() => onSelect(index)}>
            <span className={`num ${withIssues.has(index) ? "issue" : value.status}`}>
              {index + 1}
            </span>
            <span className="value-raw">{value.raw || <em>empty</em>}</span>
            <span className="muted">{(value.kind ?? "").replaceAll("_", " ")}</span>
            {state.document.page_count > 1 && <span className="muted">p{value.page}</span>}
          </button>
        </li>
      ))}
    </ol>
  );
}

/** Whether keys go into a text field; a focused select still takes the shortcuts. */
function isTyping(target: EventTarget | null): boolean {
  return target instanceof HTMLElement && target.closest("input, textarea") !== null;
}

/** The drawing named after `#` in the address, or "" if there is none or it is malformed. */
function drawingInHash(): string {
  try {
    return decodeURIComponent(window.location.hash.slice(1));
  } catch {
    return "";
  }
}

/** Whether `loc` names a stored document or title block key that the schema does not have. */
function unknownKey(document: GoldDocument, loc: Issue["loc"]): boolean {
  const [first, second] = loc;
  if (loc.length === 1)
    return !DOCUMENT_FIELDS.includes(String(first)) && String(first) in document;
  if (loc.length === 2 && first === "title_block") {
    return !TITLE_BLOCK_FIELDS.includes(String(second)) && String(second) in document.title_block;
  }
  return false;
}

function withoutKey(document: GoldDocument, loc: Issue["loc"]): GoldDocument {
  const omit = <T extends object>(record: T, key: string): T =>
    Object.fromEntries(Object.entries(record).filter(([name]) => name !== key)) as T;
  return loc[0] === "title_block"
    ? { ...document, title_block: omit(document.title_block, String(loc[1])) }
    : omit(document, String(loc[0]));
}
