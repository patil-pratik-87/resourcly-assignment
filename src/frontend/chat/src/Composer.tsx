import { useEffect, useRef, useState } from "react";
import { fileKind, fileSize, middleCut, overCap } from "./describe";
import type { AgentInfo, RequestRecord } from "./types";

const ACCEPT = ".pdf,.png,.jpg,.jpeg,.tif,.tiff,application/pdf,image/png,image/jpeg,image/tiff";

/** An earlier item or value the next message asks about, as the API names it, and its label. */
export interface About {
  ref: string;
  label: string;
}

interface Props {
  onSend: (text: string, files: File[]) => Promise<RequestRecord>;
  /** The attached files; the chat adds the ones dropped anywhere on it. */
  files: File[];
  onFiles: (update: (current: File[]) => File[]) => void;
  dragging: boolean;
  /** The server's upload caps, checked before sending; null until the agent has answered. */
  caps: Pick<AgentInfo, "max_file_mb" | "max_files"> | null;
  /** The earlier item the next message asks about, and how to stop asking about it. */
  about?: About | null;
  onClearAbout?: () => void;
  /** Start the next message in a new conversation; left out when there is none to leave. */
  onNewConversation?: () => void;
}

/** The message being written: text and any number of files, sent as one request. */
export function Composer({
  onSend,
  files,
  onFiles: setFiles,
  dragging,
  caps,
  about = null,
  onClearAbout,
  onNewConversation,
}: Props) {
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const picker = useRef<HTMLInputElement>(null);
  const field = useRef<HTMLTextAreaElement>(null);

  const empty = text.trim() === "" && files.length === 0;

  // Asked about an earlier item, the person types next.
  useEffect(() => {
    if (about) field.current?.focus();
  }, [about]);

  async function send() {
    if (empty || sending) return;
    const refused = caps && overCap(files, caps);
    if (refused) {
      setError(`Not sent: ${refused}`);
      return;
    }
    setSending(true);
    setError(null);
    try {
      await onSend(text.trim(), files);
      setText("");
      setFiles(() => []);
    } catch (cause) {
      setError(`Not sent: ${(cause as Error).message}`);
    } finally {
      setSending(false);
      field.current?.focus();
    }
  }

  return (
    <form
      className={`composer${dragging ? " ready" : ""}`}
      onSubmit={(event) => {
        event.preventDefault();
        void send();
      }}
    >
      <div className="composer-box">
        {about && (
          <div className="about-chip">
            <span>
              About <strong title={about.label}>{middleCut(about.label, 40)}</strong>
              {files.length > 0 && <span className="muted"> (not with new files)</span>}
            </span>
            <button
              type="button"
              aria-label={`Stop asking about ${about.label}`}
              onClick={() => {
                onClearAbout?.();
                field.current?.focus();
              }}
            >
              ×
            </button>
          </div>
        )}
        {files.length > 0 && (
          <ul className="composer-files" aria-label="Attached files">
            {files.map((file, index) => (
              <li key={`${file.name}-${index}`} className="file-chip">
                <FileGlyph type={file.type} name={file.name} />
                <span className="file-chip-name" title={`${file.name}, ${fileSize(file.size)}`}>
                  {middleCut(file.name, 26)}
                </span>
                <button
                  type="button"
                  aria-label={`Remove ${file.name}`}
                  onClick={() => setFiles((current) => current.filter((_, i) => i !== index))}
                >
                  ×
                </button>
              </li>
            ))}
          </ul>
        )}
        <div className="composer-row">
          <button
            type="button"
            className="composer-attach"
            aria-label="Attach files"
            title="Attach drawings or photos"
            onClick={() => picker.current?.click()}
          >
            <svg viewBox="0 0 20 20" aria-hidden>
              <path d="M13.5 6.5 7.8 12.2a1.8 1.8 0 0 0 2.5 2.5l6-6a3.4 3.4 0 0 0-4.8-4.8l-6.2 6.2a5 5 0 0 0 7 7l4.4-4.4" />
            </svg>
          </button>
          <input
            ref={picker}
            type="file"
            multiple
            accept={ACCEPT}
            hidden
            data-testid="file-picker"
            onChange={(event) => {
              const picked = Array.from(event.target.files ?? []);
              setFiles((current) => [...current, ...picked]);
              event.target.value = "";
            }}
          />
          <label className="visually-hidden" htmlFor="composer-text">
            Message
          </label>
          <textarea
            id="composer-text"
            ref={field}
            rows={1}
            value={text}
            placeholder={
              files.length > 0
                ? "Add a note or a question, or just send"
                : about
                  ? "Ask about it"
                  : "Ask something, or drop drawings and photos anywhere"
            }
            onChange={(event) => setText(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                event.preventDefault();
                void send();
              }
            }}
          />
          <button type="submit" className="composer-send" disabled={empty || sending}>
            {sending ? "Sending" : "Send"}
          </button>
        </div>
      </div>
      {(error || onNewConversation) && (
        <div className="composer-foot">
          {error && (
            <p className="composer-error" role="alert">
              {error}
            </p>
          )}
          {onNewConversation && (
            <button
              type="button"
              className="quiet new-conversation"
              onClick={() => {
                onNewConversation();
                field.current?.focus();
              }}
            >
              New conversation
            </button>
          )}
        </div>
      )}
    </form>
  );
}

const GLYPHS = { pdf: "PDF", image: "IMG", other: "FILE" };

export function FileGlyph({ type, name }: { type: string | null; name: string }) {
  const kind = fileKind(type, name);
  return (
    <span className={`file-glyph ${kind}`} aria-hidden>
      {GLYPHS[kind]}
    </span>
  );
}
