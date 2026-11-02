// Plain words and numbers for what the agent did, kept apart from the components so they can be
// tested on their own.
import type { ReadProgress, RequestItem, RequestRecord, Route, TraceEvent } from "./types";

export const ROUTE_LABELS: Record<Route, string> = {
  drawing: "Technical drawing",
  photo: "Photo of a part",
  text: "Text question",
  other: "Fits no case",
};

/** The router's layers by the name it records; an unknown layer shows as recorded. */
const LAYER_LABELS: Record<string, string> = {
  stub: "stand-in rule",
  structure: "structure rules",
  probe: "image probe",
  vlm: "vision-language model",
  none: "no layer, none was sure",
};

export function layerLabel(layer: string): string {
  return LAYER_LABELS[layer.toLowerCase()] ?? layer;
}

/** Which router layer decided, as a sentence. */
export function chosenBy(layer: string): string {
  if (layer.toLowerCase() === "none") return `Chosen by ${layerLabel(layer)}.`;
  const known = layer.toLowerCase() in LAYER_LABELS;
  return known ? `Chosen by the ${layerLabel(layer)}.` : `Chosen by the ${layer} layer.`;
}

export function isActive(item: RequestItem): boolean {
  return item.status === "routing" || item.status === "queued" || item.status === "reading";
}

/** One line on where an item is, for the chat card and the request list. */
export function statusLine(item: RequestItem): string {
  switch (item.status) {
    case "routing":
      return "Choosing the case";
    case "queued":
      return "Waiting for the reader";
    case "reading":
      return item.progress ? progressLine(item.progress) : "Opening the drawing";
    case "done": {
      const values = plural(item.values ?? 0, "value");
      const issues = item.issues ? `, ${plural(item.issues, "schema issue")}` : "";
      return `${values} read${issues}`;
    }
    case "answered":
      return "Answered";
    case "failed":
      return item.error ?? "Failed";
  }
}

export function progressLine(progress: ReadProgress): string {
  const step = Math.min(progress.done + 1, progress.total);
  const what = progress.boxes.length > 0 ? "callout" : "page";
  const page = progress.pages > 1 ? ` on page ${progress.page} of ${progress.pages}` : "";
  return progress.total === 0
    ? "Reading the text layer"
    : `Reading ${what} ${step} of ${progress.total}${page}`;
}

/** The share of the read that is done, from 0 to 1. */
export function progressShare(progress: ReadProgress | null): number {
  if (!progress || progress.total === 0) return 0;
  return Math.min(1, progress.done / progress.total);
}

/** How many items of a request are in each state, for the line over a bulk upload. */
export function tally(items: RequestItem[]): string {
  const count = (test: (item: RequestItem) => boolean) => items.filter(test).length;
  const parts = [
    [count((item) => item.status === "done"), "read"],
    [count((item) => item.status === "answered"), "answered"],
    [count(isActive), "in progress"],
    [count((item) => item.status === "failed"), "failed"],
  ] as const;
  const said = parts.filter(([n]) => n > 0).map(([n, word]) => `${n} ${word}`);
  return `${plural(items.length, "file")}: ${said.join(", ")}`;
}

/** How long a read has run, as "0:42" or "12:05". */
export function elapsed(startedAt: string | null, now = Date.now()): string | null {
  if (!startedAt) return null;
  const seconds = Math.max(0, Math.floor((now - new Date(startedAt).getTime()) / 1000));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

/** A long name cut in the middle, so its end, which tells similar names apart, stays visible. */
export function middleCut(name: string, max = 28): string {
  if (name.length <= max) return name;
  const tail = Math.ceil((max - 1) * 0.55);
  return `${name.slice(0, max - 1 - tail)}…${name.slice(-tail)}`;
}

const IMAGE_NAME = /\.(png|jpe?g|tiff?|gif|bmp|webp|heic)$/i;

/** What a file looks like it is, for its icon: from its media type, else from its name. */
export function fileKind(type: string | null, name: string): "pdf" | "image" | "other" {
  if (type === "application/pdf" || (!type && name.toLowerCase().endsWith(".pdf"))) return "pdf";
  if (type?.startsWith("image/") || (!type && IMAGE_NAME.test(name))) return "image";
  return "other";
}

const MB = 1024 * 1024;

/** Why the server would refuse these files, in its own words, or null when it would take them. */
export function overCap(
  files: { name: string; size: number }[],
  caps: { max_file_mb: number; max_files: number },
): string | null {
  if (files.length > caps.max_files)
    return `A message can carry at most ${caps.max_files} files; this one has ${files.length}.`;
  const big = files.find((file) => file.size > caps.max_file_mb * MB);
  if (!big) return null;
  const size = (big.size / MB).toFixed(1);
  return `${big.name} is ${size} MB; each file can be at most ${caps.max_file_mb} MB.`;
}

/** A reason as a sentence: a router layer may write its reason as a lower-case fragment. */
export function sentence(text: string): string {
  const trimmed = text.trim();
  if (!trimmed) return trimmed;
  const capital = trimmed[0]!.toUpperCase() + trimmed.slice(1);
  return /[.!?]$/.test(capital) ? capital : `${capital}.`;
}

export function plural(count: number, word: string): string {
  return `${count} ${word}${count === 1 ? "" : "s"}`;
}

export function fileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** "14:02" today, "Yesterday 14:02", or "28 Oct 14:02". */
export function sentAt(iso: string, now = new Date()): string {
  const when = new Date(iso);
  const time = when.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
  const day = (date: Date) => new Date(date.getFullYear(), date.getMonth(), date.getDate());
  const days = Math.round((day(now).getTime() - day(when).getTime()) / 86_400_000);
  if (days === 0) return time;
  if (days === 1) return `Yesterday ${time}`;
  const date = when.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
  return `${date} ${time}`;
}

export function shortId(requestId: string): string {
  return requestId.slice(0, 8);
}

export function duration(ms: number): string {
  if (ms < 1) return "under 1 ms";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}

/** The item a viewer opens first: the newest finished drawing, else the newest item. */
export function firstItem(requests: RequestRecord[]): { requestId: string; itemId: string } | null {
  for (const record of requests) {
    const item = record.items.find((candidate) => candidate.status === "done");
    if (item) return { requestId: record.request_id, itemId: item.item_id };
  }
  const record = requests[0];
  const item = record?.items[0];
  return record && item ? { requestId: record.request_id, itemId: item.item_id } : null;
}

/** The request a typed id names: an exact id, else the one id among `requests` it starts. */
export function matchRequest(typed: string, requests: RequestRecord[]): string | null {
  const id = typed.trim().toLowerCase();
  if (!id) return null;
  const exact = requests.find((record) => record.request_id === id);
  if (exact) return exact.request_id;
  const starts = requests.filter((record) => record.request_id.startsWith(id));
  return starts.length === 1 ? starts[0]!.request_id : null;
}

/** What one router layer made of an item, as its trace step records it. */
export interface LayerVerdict {
  layer: string;
  decided: boolean;
  route: Route | null;
  confidence: number | null;
  reason: string;
  error: string | null;
  duration_ms: number;
}

/** One step of the trace; a routing step carries the verdict of every layer the router asked. */
export interface TraceStep {
  event: TraceEvent;
  /** The item the step is about, when it names one. */
  item: string | null;
  layers: LayerVerdict[];
}

/**
 * The trace as steps: each router layer's step joins the routing step of its item. The router
 * records its layers as `route.<layer>` before the agent records `router.route` for the item.
 */
export function traceSteps(events: TraceEvent[]): TraceStep[] {
  const steps: TraceStep[] = [];
  let pending: TraceEvent[] = [];
  for (const event of events) {
    if (event.step.startsWith("route.")) {
      pending.push(event);
      continue;
    }
    const routing = event.step === "router.route";
    steps.push({
      event,
      item: itemOf(event.input),
      layers: routing ? pending.map(layerVerdict) : [],
    });
    if (routing) pending = [];
  }
  // The layers of an item still being routed: its routing step is stored when the router ends.
  if (pending.length > 0) {
    steps.push({ event: pending[0]!, item: null, layers: pending.map(layerVerdict) });
  }
  return steps;
}

function layerVerdict(event: TraceEvent): LayerVerdict {
  const output = event.output;
  const route = typeof output.route === "string" ? (output.route as Route) : null;
  return {
    layer: event.step.slice("route.".length),
    decided: output.decided === true,
    route,
    confidence: typeof output.confidence === "number" ? output.confidence : null,
    reason: typeof output.reason === "string" ? output.reason : "",
    error: event.error,
    duration_ms: event.duration_ms,
  };
}

/** The item a step is about: the agent's steps name it, a read names its drawing. */
function itemOf(input: Record<string, unknown>): string | null {
  const found = input.item ?? input.drawing;
  return typeof found === "string" ? found : null;
}
