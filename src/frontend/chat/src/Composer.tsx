import { useRef, useState } from "react";
import { fileKind, fileSize, middleCut, overCap } from "./describe";
import type { AgentInfo, RequestRecord } from "./types";

const ACCEPT = ".pdf,.png,.jpg,.jpeg,.tif,.tiff,application/pdf,image/png,image/jpeg,image/tiff";

interface Props {
  onSend: (text: string, files: File[]) => Promise<RequestRecord>;
  /** The attached files; the chat adds the ones dropped anywhere on it. */
  files: File[];
  onFiles: (update: (current: File[]) => File[]) => void;
  dragging: boolean;
  /** The server's upload caps, checked before sending; null until the agent has answered. */
  caps: Pick<AgentInfo, "max_file_mb" | "max_files"> | null;
}

/** The message being written: text and any number of files, sent as one request. */
export function Composer({ onSend, files, onFiles: setFiles, dragging, caps }: Props) {
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const picker = useRef<HTMLInputElement>(null);
  const field = useRef<HTMLTextAreaElement>(null);

  const empty = text.trim() === "" && files.length === 0;

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
                ? "Add a note, or just send"
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
      {error && (
        <p className="composer-error" role="alert">
          {error}
        </p>
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
