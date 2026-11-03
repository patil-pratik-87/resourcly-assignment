import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { AgentApi, SendOptions } from "./api";
import { type About, Composer } from "./Composer";
import { ItemCard } from "./ItemCard";
import { DEMO_NOTE, plural, sentAt, shortId, tally } from "./describe";
import type { AgentInfo, RequestItem, RequestRecord } from "./types";

/** The chat shows this many of the latest requests; the requests screen has them all. */
const SHOWN = 30;
/** A message names this many of its files and counts the rest, when there are two or more. */
const NAMED_FILES = 6;

interface Props {
  api: AgentApi;
  requests: RequestRecord[];
  loaded: boolean;
  onSend: (text: string, files: File[], options?: SendOptions) => Promise<RequestRecord>;
  onOpen: (requestId: string, itemId: string) => void;
  info: AgentInfo | null;
}

export function Chat({ api, requests, loaded, onSend, onOpen, info }: Props) {
  const thread = useRef<HTMLDivElement>(null);
  const [dragging, setDragging] = useState(false);
  const [files, setFiles] = useState<File[]>([]);
  const [about, setAbout] = useState<About | null>(null);
  // The next message joins the newest message's conversation, unless asked to start a new one.
  const [fresh, setFresh] = useState(false);
  const shown = requests.slice(0, SHOWN).reverse();
  const newest = requests[0]?.request_id;
  const conversationId = fresh ? null : (requests[0]?.conversation_id ?? null);

  async function send(text: string, sent: File[], ask: string[] = []) {
    const record = await onSend(text, sent, { conversationId, about: ask });
    setFresh(false);
    return record;
  }

  // Keep the newest message in view when one is sent or arrives, and while its cards grow,
  // unless the person has scrolled up to read.
  const pinned = useRef(true);
  useLayoutEffect(() => {
    const box = thread.current;
    if (!box) return;
    box.scrollTop = box.scrollHeight;
    pinned.current = true;
  }, [newest, loaded]);
  useEffect(() => {
    const box = thread.current;
    const column = box?.firstElementChild;
    if (!box || !column || typeof ResizeObserver === "undefined") return;
    const onScroll = () => {
      pinned.current = box.scrollHeight - box.scrollTop - box.clientHeight < 80;
    };
    const observer = new ResizeObserver(() => {
      if (pinned.current) box.scrollTop = box.scrollHeight;
    });
    box.addEventListener("scroll", onScroll);
    observer.observe(column);
    return () => {
      box.removeEventListener("scroll", onScroll);
      observer.disconnect();
    };
  }, []);

  // A drag anywhere over the chat attaches the files to the message being written.
  const depth = useRef(0);
  useEffect(() => {
    const hasFiles = (event: DragEvent) => event.dataTransfer?.types.includes("Files") ?? false;
    const enter = (event: DragEvent) => {
      if (!hasFiles(event)) return;
      depth.current += 1;
      setDragging(true);
    };
    const leave = () => {
      depth.current = Math.max(0, depth.current - 1);
      if (depth.current === 0) setDragging(false);
    };
    const over = (event: DragEvent) => {
      if (hasFiles(event)) event.preventDefault();
    };
    const drop = (event: DragEvent) => {
      if (!hasFiles(event)) return;
      event.preventDefault();
      depth.current = 0;
      setDragging(false);
      const dropped = Array.from(event.dataTransfer?.files ?? []);
      setFiles((current) => [...current, ...dropped]);
    };
    window.addEventListener("dragenter", enter);
    window.addEventListener("dragleave", leave);
    window.addEventListener("dragover", over);
    window.addEventListener("drop", drop);
    return () => {
      window.removeEventListener("dragenter", enter);
      window.removeEventListener("dragleave", leave);
      window.removeEventListener("dragover", over);
      window.removeEventListener("drop", drop);
    };
  }, []);

  return (
    <main className="chat">
      <div className="chat-thread" ref={thread}>
        <div className="chat-column">
          {loaded && shown.length === 0 && <Welcome />}
          {shown.map((record, index) => (
            <Exchange
              key={record.request_id}
              api={api}
              record={record}
              requests={requests}
              opensConversation={
                index > 0 && record.conversation_id !== shown[index - 1]!.conversation_id
              }
              onOpen={onOpen}
              onAsk={(text, ref) => void send(text, [], [ref]).catch(() => {})}
              onAskAbout={setAbout}
            />
          ))}
        </div>
      </div>
      <Composer
        onSend={async (text, sent) => {
          const record = await send(text, sent, about && sent.length === 0 ? [about.ref] : []);
          setAbout(null);
          return record;
        }}
        files={files}
        onFiles={setFiles}
        dragging={dragging}
        caps={info}
        about={about}
        onClearAbout={() => setAbout(null)}
        onNewConversation={
          requests.length > 0 && !fresh
            ? () => {
                setFresh(true);
                setAbout(null);
              }
            : undefined
        }
      />
      {dragging && (
        <div className="chat-drop" aria-hidden>
          <div className="chat-drop-sheet">
            <strong>Drop to attach</strong>
            <span>Drawings as PDF, photos as PNG, JPEG or TIFF. As many as you like.</span>
          </div>
        </div>
      )}
    </main>
  );
}

function Exchange({
  api,
  record,
  requests,
  opensConversation,
  onOpen,
  onAsk,
  onAskAbout,
}: {
  api: AgentApi;
  record: RequestRecord;
  /** Every request, to name the earlier items this one is about. */
  requests: RequestRecord[];
  /** Whether it starts a conversation after an earlier one in the thread. */
  opensConversation: boolean;
  onOpen: (requestId: string, itemId: string) => void;
  /** Ask a question about an earlier item or value, named as the API's `about` names it. */
  onAsk: (text: string, about: string) => void;
  /** Make an item of this request what the next message asks about. */
  onAskAbout: (about: About) => void;
}) {
  const files = record.items.filter((item) => item.kind === "file");
  const named = files.length > NAMED_FILES + 1 ? NAMED_FILES : files.length;
  return (
    <article className="exchange" aria-label={`Request ${record.request_id}`}>
      {opensConversation && (
        <p className="conversation-break">
          <span>New conversation</span>
        </p>
      )}
      <div className="said">
        <div className="said-meta">
          <span>You</span>
          <time dateTime={record.created_at}>{sentAt(record.created_at)}</time>
        </div>
        {record.text && <p className="said-text">{record.text}</p>}
        {(record.about ?? []).length > 0 && (
          <p className="said-about">
            About {(record.about ?? []).map((ref) => aboutLabel(ref, requests)).join(", ")}
          </p>
        )}
        {files.length > 0 && (
          <ul className="said-files">
            {files.slice(0, named).map((item) => (
              <li key={item.item_id}>{item.name}</li>
            ))}
            {files.length > named && (
              <li className="said-more">and {plural(files.length - named, "more file")}</li>
            )}
          </ul>
        )}
      </div>
      <div className={`reply${record.items.length > 1 ? " bulk" : ""}`}>
        <div className="said-meta">
          <span>Agent</span>
          <span className="reply-id" title={`Request ${record.request_id}`}>
            Request {shortId(record.request_id)}
          </span>
          {record.demo && (
            <span className="demo-tag" title={DEMO_NOTE}>
              Demo
            </span>
          )}
        </div>
        {record.items.length > 1 && (
          <p className="tally" role="status" aria-label="Progress">
            {tally(record.items)}
          </p>
        )}
        {record.items.map((item) => (
          <ItemCard
            key={item.item_id}
            api={api}
            requestId={record.request_id}
            item={item}
            onOpen={() => onOpen(record.request_id, item.item_id)}
            onPick={(cited) =>
              onAsk(record.text, `${cited.request_id}/${cited.item_id}/${cited.ref}`)
            }
            onAskAbout={
              askable(item)
                ? () =>
                    onAskAbout({ ref: `${record.request_id}/${item.item_id}`, label: item.name })
                : undefined
            }
          />
        ))}
      </div>
    </article>
  );
}

/** Whether a later message can ask about an item: a drawing read, or a photo answered. */
function askable(item: RequestItem): boolean {
  if (item.kind !== "file") return false;
  if (item.route?.route === "drawing") return item.values !== null && item.status === "done";
  return item.route?.route === "photo" && item.status === "answered";
}

/** An earlier item or value as a person reads it: the file's name, and the value's id. */
export function aboutLabel(ref: string, requests: RequestRecord[]): string {
  const [requestId, itemId, valueId] = ref.split("/");
  const found = requests
    .find((record) => record.request_id === requestId)
    ?.items.find((item) => item.item_id === itemId);
  const name = found?.name ?? itemId ?? ref;
  return valueId ? `${valueId} of ${name}` : name;
}

function Welcome() {
  return (
    <section className="welcome">
      <h1>Send a drawing, a photo, or a question.</h1>
      <p>
        The agent decides what each file is. A technical drawing comes back as JSON with every value
        on it, and a photo of a part with what the NTSB reports say about it. Ask about a file in
        the same message, or later with Ask about this. Attach many files at once and each is done
        in turn while you watch.
      </p>
      <ul className="welcome-cases">
        <li>
          <span className="route-tag drawing">Technical drawing</span>
          Every dimension, tolerance and note, as JSON
        </li>
        <li>
          <span className="route-tag photo">Photo of a part</span>
          What is wrong and what to do, citing the reports
        </li>
        <li>
          <span className="route-tag text">Text question</span>
          An answer from the reports, each fact citing its page
        </li>
        <li>
          <span className="route-tag other">Fits no case</span>
          Said plainly, with the reason
        </li>
      </ul>
    </section>
  );
}
