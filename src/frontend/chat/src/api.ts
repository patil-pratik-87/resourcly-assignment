// The chat agent's HTTP API; see the API section of docs/chat-ui.md.
import { figureNumber } from "./describe";
import type { AgentInfo, ReadDocument, RequestRecord, RequestTrace } from "./types";

type Fetch = (url: string, init?: RequestInit) => Promise<Response>;

export type AgentApi = ReturnType<typeof createAgentApi>;

export function createAgentApi(fetch: Fetch) {
  const request = (requestId: string) => `/api/requests/${encodeURIComponent(requestId)}`;
  const item = (requestId: string, itemId: string) =>
    `${request(requestId)}/items/${encodeURIComponent(itemId)}`;

  async function json<T>(path: string, init?: RequestInit): Promise<T> {
    let response: Response;
    try {
      response = await fetch(path, init);
    } catch {
      // The browser says only "Failed to fetch" when nothing answers.
      throw new Error("The server could not be reached");
    }
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail ?? `${response.status} ${response.statusText}`);
    }
    return response.json();
  }

  return {
    agent: () => json<AgentInfo>("/api/agent"),

    /** One message: its text and every file, sent as one request. */
    send(text: string, files: File[]): Promise<RequestRecord> {
      const form = new FormData();
      form.append("text", text);
      for (const file of files) form.append("files", file, file.name);
      return json<RequestRecord>("/api/requests", { method: "POST", body: form });
    },

    requests: () => json<RequestRecord[]>("/api/requests"),

    request: (requestId: string) => json<RequestRecord>(request(requestId)),

    trace: (requestId: string) => json<RequestTrace>(`${request(requestId)}/trace`),

    result: (requestId: string, itemId: string) =>
      json<ReadDocument>(`${item(requestId, itemId)}/result`),

    downloadUrl: (requestId: string, itemId: string) =>
      `${item(requestId, itemId)}/result?download=true`,

    /** A page of an uploaded file as an image; a photo is its one page. */
    pageUrl: (requestId: string, itemId: string, page: number, dpi = 150) =>
      `${item(requestId, itemId)}/pages/${page}.png?dpi=${dpi}`,

    /** A report figure, such as 18-061/fig05, as an image of at most `maxSide` pixels a side. */
    figureUrl(figure: string, maxSide: number) {
      const report = figure.split("/")[0]!;
      return `/api/reports/${encodeURIComponent(report)}/figures/${figureNumber(figure)}.png?max_side=${maxSide}`;
    },
  };
}
