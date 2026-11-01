// The backend's HTTP API; see the API table in the README.
import type { StoredDocument } from "./document";
import type { DrawingSummary, GoldDocument, Issue } from "./types";

type Fetch = (url: string, init?: RequestInit) => Promise<Response>;

/** Pages render at 150 dpi: sharp enough to read callouts when zoomed, and quick to load. */
const PAGE_DPI = 150;

export type Api = ReturnType<typeof createApi>;

export type SaveResult = { ok: true; document: GoldDocument } | { ok: false; issues: Issue[] };

export function createApi(fetch: Fetch) {
  const url = (drawing: string) => `/api/drawings/${encodeURIComponent(drawing)}`;

  /** Fails on any error status except, when `issues` is set, a 422 that lists issues. */
  async function send(path: string, init?: RequestInit, issues = false): Promise<Response> {
    const response = await fetch(path, init);
    if (response.ok || (issues && response.status === 422)) return response;
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail ?? `${response.status} ${response.statusText}`);
  }

  const json = { "Content-Type": "application/json" };

  // Requests go to the drawing that was opened, never to the `drawing` field of the document:
  // a file whose field names another drawing must not overwrite that drawing's gold.
  return {
    async drawings(): Promise<DrawingSummary[]> {
      return (await send("/api/drawings")).json();
    },

    async document(drawing: string): Promise<StoredDocument> {
      return (await send(url(drawing))).json();
    },

    async check(drawing: string, document: GoldDocument): Promise<Issue[]> {
      const response = await send(`${url(drawing)}/check`, {
        method: "POST",
        headers: json,
        body: JSON.stringify(document),
      });
      return response.json();
    },

    pageImage(drawing: string, page: number): string {
      return `${url(drawing)}/pages/${page}.png?dpi=${PAGE_DPI}`;
    },

    async save(drawing: string, document: GoldDocument): Promise<SaveResult> {
      const response = await send(
        url(drawing),
        {
          method: "PUT",
          headers: json,
          body: JSON.stringify(document),
        },
        true,
      );
      const body = await response.json();
      if (response.ok) return { ok: true, document: body };
      // A 422 without issues (an unreadable PDF, say) is a failure, not a list to show.
      if (!Array.isArray(body.issues)) throw new Error(body.detail ?? "422 Unprocessable Entity");
      return { ok: false, issues: body.issues };
    },
  };
}
