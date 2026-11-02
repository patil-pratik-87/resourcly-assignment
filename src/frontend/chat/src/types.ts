// The chat requests as the API sends them; see RequestRecord in src/resourcly/models.py.
import type { Bbox } from "./bbox";

/** The case the router picks for an item; `other` is a file that fits no case. */
export type Route = "drawing" | "photo" | "text" | "other";

/** The router's answer for one item; see Routing in src/resourcly/models.py. */
export interface Routing {
  request_id: string;
  route: Route;
  /** The layer that decided, or none when no layer was sure. */
  layer: string;
  /** Absent when no layer was sure. */
  confidence: number | null;
  reason: string;
  probabilities: Record<string, number>;
  elapsed_ms: number;
}

export interface ReadProgress {
  page: number;
  pages: number;
  done: number;
  total: number;
  /** The callouts found on `page`; the first `page_done` of them are read. */
  boxes: Bbox[];
  page_done: number;
  latest: string[];
}

export type ItemStatus = "routing" | "queued" | "reading" | "done" | "failed" | "answered";

export interface RequestItem {
  item_id: string;
  kind: "file" | "text";
  name: string;
  media_type: string | null;
  size: number;
  pages: number;
  route: Routing | null;
  status: ItemStatus;
  progress: ReadProgress | null;
  reply: string | null;
  values: number | null;
  issues: number | null;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface RequestRecord {
  request_id: string;
  text: string;
  created_at: string;
  items: RequestItem[];
  status: "working" | "failed" | "done";
}

export interface TraceEvent {
  request_id: string;
  step: string;
  called: string;
  input: Record<string, unknown>;
  output: Record<string, unknown>;
  error: string | null;
  started_at: string;
  duration_ms: number;
}

export interface RequestTrace {
  request_id: string;
  events: TraceEvent[];
}

export interface AgentInfo {
  reader: string;
  router: string;
  /** The upload caps: the server refuses a message over either one. */
  max_file_mb: number;
  max_files: number;
}

/** A value of a read drawing, as far as the screen needs it; the rest is shown as JSON. */
export interface ReadValue {
  id?: string;
  raw?: string;
  kind?: string;
  meaning?: string;
  page?: number;
  bbox?: unknown;
  [key: string]: unknown;
}

export interface ReadDocument {
  drawing?: string;
  page_count?: number;
  values?: ReadValue[];
  [key: string]: unknown;
}
