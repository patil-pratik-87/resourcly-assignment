import type { AgentApi } from "../api";
import type {
  PhotoAnswer,
  ReadDocument,
  RequestItem,
  RequestRecord,
  RequestTrace,
  Routing,
  TraceEvent,
} from "../types";

export function routing(overrides: Partial<Routing> = {}): Routing {
  return {
    request_id: "r1",
    route: "drawing",
    layer: "stub",
    confidence: 0.7,
    reason: "The first page has 1797 vector paths, at least 300: drawn like a technical drawing.",
    probabilities: {},
    elapsed_ms: 34.6,
    ...overrides,
  };
}

export function item(overrides: Partial<RequestItem> = {}): RequestItem {
  return {
    item_id: "ctc",
    kind: "file",
    name: "ctc.pdf",
    media_type: "application/pdf",
    size: 55_000,
    pages: 2,
    route: routing(),
    status: "done",
    progress: null,
    reply: null,
    answer: null,
    values: 3,
    issues: 0,
    error: null,
    started_at: "2026-11-01T10:00:01.000+00:00",
    finished_at: "2026-11-01T10:01:00.000+00:00",
    ...overrides,
  };
}

export function record(overrides: Partial<RequestRecord> = {}): RequestRecord {
  return {
    request_id: "r1",
    text: "read this",
    created_at: "2026-11-01T10:00:00.000+00:00",
    items: [item()],
    status: "done",
    ...overrides,
  };
}

/** A photo of a cracked spar answered from the reports: two findings, three actions, three figures. */
export function photoAnswer(overrides: Partial<PhotoAnswer> = {}): PhotoAnswer {
  const cite = (report: string, page: number, figure?: number) => ({
    source: figure ? `${report} fig${String(figure).padStart(2, "0")}` : `${report} p${page}`,
    report,
    page,
    figure: figure ? `${report}/fig${String(figure).padStart(2, "0")}` : null,
  });
  return {
    not_in_reports: false,
    kept_out: null,
    matched: true,
    answer: "The spar cap has a fatigue crack that started at a fastener hole.",
    findings: [
      {
        statement: "The crack grew by fatigue from the lower forward fastener hole.",
        citation: cite("18-061", 7, 5),
      },
      { statement: "The spar cap met the specified hardness.", citation: cite("18-061", 3) },
    ],
    actions: [
      {
        action: "Inspect the spar cap fastener holes with eddy current.",
        basis: "stated",
        citation: cite("18-061", 12),
        quote: "inspect the spar cap fastener holes using eddy current",
      },
      {
        action: "Check the other spar cap for the same crack.",
        basis: "inferred",
        citation: cite("18-061", 7, 5),
      },
      { action: "Replace the cracked spar cap before flight.", basis: "inferred", citation: null },
    ],
    figures: [
      {
        figure: "18-061/fig05",
        report: "18-061",
        section: "spar_fatigue_N106ER",
        failure_mode: "fatigue",
        score: 0.6241,
      },
      {
        figure: "18-061/fig06",
        report: "18-061",
        section: "spar_fatigue_N106ER",
        failure_mode: "fatigue",
        score: 0.5815,
      },
      {
        figure: "24-013/fig02",
        report: "24-013",
        section: "new_extrusion",
        failure_mode: "reference_no_defect",
        score: 0.4102,
      },
    ],
    ...overrides,
  };
}

/** A read drawing of two pages: values 1 and 2 on page 1, value 3 on page 2. */
export function readDocument(): ReadDocument {
  const value = (n: number, page: number, bbox: number[]) => ({
    id: `ctc01-0${n}`,
    raw: `⌀${n}0 ±0.1`,
    kind: "diameter",
    meaning: `A diameter of ${n}0 mm.`,
    page,
    bbox,
  });
  return {
    drawing: "ctc",
    page_count: 2,
    title_block: { units: "mm" },
    features: [{ id: "callout_01" }],
    values: [
      value(1, 1, [0.1, 0.1, 0.2, 0.2]),
      value(2, 1, [0.5, 0.5, 0.6, 0.6]),
      value(3, 2, [0.3, 0.3, 0.4, 0.4]),
    ],
  };
}

export function event(overrides: Partial<TraceEvent> = {}): TraceEvent {
  return {
    request_id: "r1",
    step: "requests.receive",
    called: "agent",
    input: {},
    output: {},
    error: null,
    started_at: "2026-11-01T10:00:00.000+00:00",
    duration_ms: 0.2,
    ...overrides,
  };
}

/** The trace of a request of one drawing, routed by a router of two layers. */
export function trace(requestId: string): RequestTrace {
  const attachment = { name: "ctc.pdf", media_type: "application/pdf", bytes: 55_000 };
  return {
    request_id: requestId,
    events: [
      event({ request_id: requestId, input: { files: ["ctc.pdf"] } }),
      event({
        request_id: requestId,
        step: "uploads.save",
        called: "upload store",
        input: { name: "ctc.pdf", bytes: 55_000, item: "ctc" },
        output: { media_type: "application/pdf", pages: 1 },
        duration_ms: 7.1,
      }),
      event({
        request_id: requestId,
        step: "route.structure",
        called: "router layers-v0 (layers): structure rules",
        input: { text_chars: 9, attachment },
        output: { decided: false, route: null, confidence: null, reason: "not sure" },
        duration_ms: 12,
      }),
      event({
        request_id: requestId,
        step: "route.probe",
        called: "router layers-v0 (layers): image probe",
        input: { text_chars: 9, attachment },
        output: {
          decided: true,
          route: "drawing",
          confidence: 0.93,
          reason: "the probe gives drawing 0.93",
        },
        duration_ms: 230,
      }),
      event({
        request_id: requestId,
        step: "router.route",
        called: "router layers-v0 (layers)",
        input: { item: "ctc", text_chars: 9, file: "ctc.pdf" },
        output: { route: "drawing", layer: "probe", confidence: 0.93 },
        duration_ms: 243,
      }),
      event({
        request_id: requestId,
        step: "drawings.read",
        called: "reader textlayer-v0 (textlayer)",
        input: { drawing: "ctc" },
        output: { values: 3, schema_issues: 0 },
        duration_ms: 5.1,
      }),
    ],
  };
}

/**
 * The agent at its HTTP boundary, holding requests in memory. `sent` records each message; a
 * test changes `requests` to move the agent on, and the next poll sees it. `stored` holds the
 * requests the API no longer lists but can still look up.
 */
export function fakeAgentApi(initial: RequestRecord[] = []) {
  const state = {
    requests: initial,
    stored: [] as RequestRecord[],
    sent: [] as { text: string; files: File[] }[],
    reply: (text: string, files: File[]): RequestRecord =>
      record({
        request_id: "new",
        text,
        status: "working",
        items: files.map((file) =>
          item({
            item_id: file.name.replace(/\.[^.]+$/, ""),
            name: file.name,
            status: "routing",
            route: null,
            values: null,
          }),
        ),
      }),
  };
  const api: AgentApi = {
    agent: async () => ({
      reader: "textlayer-v0 (textlayer)",
      router: "stub-v0 (stub)",
      failure: "dinov2-base-v1 (nearest-figures)",
      answer: "captions-v0 (captions)",
      max_file_mb: 25,
      max_files: 50,
    }),
    send: async (text, files) => {
      state.sent.push({ text, files });
      const created = state.reply(text, files);
      state.requests = [created, ...state.requests];
      return created;
    },
    requests: async () => structuredClone(state.requests),
    request: async (id) => {
      const found = [...state.requests, ...state.stored].find((r) => r.request_id === id);
      if (!found) throw new Error(`no request ${id}`);
      return structuredClone(found);
    },
    trace: async (id) => trace(id),
    result: async () => readDocument(),
    downloadUrl: (requestId, itemId) => `/download/${requestId}/${itemId}`,
    pageUrl: (requestId, itemId, page) => `/pages/${requestId}/${itemId}/${page}.png`,
    figureUrl: (figure, maxSide) => `/figures/${figure}.png?max_side=${maxSide}`,
  };
  return { api, state };
}
