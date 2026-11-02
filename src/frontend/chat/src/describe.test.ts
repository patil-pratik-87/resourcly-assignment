import { describe, expect, it } from "vitest";
import {
  elapsed,
  fileKind,
  firstItem,
  layerLabel,
  matchRequest,
  middleCut,
  overCap,
  pageOf,
  percent,
  progressLine,
  sentAt,
  sentence,
  statusLine,
  tally,
  traceSteps,
  valuesOnPage,
} from "./describe";
import { event, item, readDocument, record, trace } from "./test/fakeAgentApi";

describe("status lines", () => {
  it("counts callouts while a drawing is read, and pages when it has several", () => {
    const progress = {
      page: 2,
      pages: 3,
      done: 11,
      total: 40,
      boxes: [],
      page_done: 0,
      latest: [],
    };

    expect(progressLine({ ...progress, boxes: [[0, 0, 1, 1]] })).toBe(
      "Reading callout 12 of 40 on page 2 of 3",
    );
    expect(progressLine({ ...progress, pages: 1, done: 0, total: 1 })).toBe("Reading page 1 of 1");
  });

  it("says what came back, and why a file failed", () => {
    expect(statusLine(item({ values: 1, issues: 0 }))).toBe("1 value read");
    expect(statusLine(item({ values: 23, issues: 2 }))).toBe("23 values read, 2 issues");
    expect(statusLine(item({ status: "failed", error: "notes.txt is not a PDF" }))).toBe(
      "notes.txt is not a PDF",
    );
    expect(statusLine(item({ status: "queued" }))).toBe("Waiting for the reader");
  });

  it("counts a bulk upload's items by state", () => {
    const items = [
      item(),
      item({ status: "done" }),
      item({ status: "answered" }),
      item({ status: "reading" }),
      item({ status: "queued" }),
      item({ status: "failed" }),
    ];

    expect(tally(items)).toBe("6 files: 2 read, 1 answered, 2 in progress, 1 failed");
    expect(tally([item()])).toBe("1 file: 1 read");
  });

  it("names the router's layers in words", () => {
    expect(layerLabel("stub")).toBe("stand-in rule");
    expect(layerLabel("probe")).toBe("image probe");
    expect(layerLabel("none")).toBe("no layer, none was sure");
    expect(layerLabel("something-new")).toBe("something-new");
  });

  it("gives a confidence in percent, never rounding a doubt up to 100", () => {
    expect(percent(0.7)).toBe("70");
    expect(percent(0.9038)).toBe("90");
    expect(percent(0.998)).toBe("99.8");
    expect(percent(0.99783)).toBe("99.8");
    expect(percent(0.9999)).toBe("99.9");
    expect(percent(1)).toBe("100");
  });

  it("turns a router reason into a sentence", () => {
    expect(sentence("the probe gives photo 0.987")).toBe("The probe gives photo 0.987.");
    expect(sentence("An image is taken as a photo.")).toBe("An image is taken as a photo.");
  });

  it("cuts a long name in the middle and keeps its end", () => {
    expect(middleCut("ntsb_24-013_p4_photo.jpg", 20)).toBe("ntsb_24-…4_photo.jpg");
    expect(middleCut("short.pdf", 20)).toBe("short.pdf");
  });

  it("tells a PDF and an image from anything else", () => {
    expect(fileKind("application/pdf", "a.pdf")).toBe("pdf");
    expect(fileKind("image/jpeg", "a.jpg")).toBe("image");
    expect(fileKind(null, "photo.PNG")).toBe("image");
    expect(fileKind(null, "notes.txt")).toBe("other");
  });

  it("says why the server would refuse files, in the server's words", () => {
    const caps = { max_file_mb: 25, max_files: 2 };
    const file = (name: string, mb: number) => ({ name, size: mb * 1024 * 1024 });

    expect(overCap([file("a.pdf", 1)], caps)).toBeNull();
    expect(overCap([file("a.pdf", 31.24)], caps)).toBe(
      "a.pdf is 31.2 MB; each file can be at most 25 MB.",
    );
    expect(overCap([file("a", 1), file("b", 1), file("c", 1)], caps)).toBe(
      "A message can carry at most 2 files; this one has 3.",
    );
  });

  it("counts a read's time in minutes and seconds", () => {
    const start = "2026-11-01T10:00:00.000Z";

    expect(elapsed(start, Date.parse("2026-11-01T10:01:05.000Z"))).toBe("1:05");
    expect(elapsed(null)).toBeNull();
  });

  it("gives the time today and the date before", () => {
    const now = new Date(2026, 10, 1, 15, 0);

    expect(sentAt(new Date(2026, 10, 1, 9, 5).toISOString(), now)).toBe("09:05");
    expect(sentAt(new Date(2026, 9, 31, 9, 5).toISOString(), now)).toBe("Yesterday 09:05");
    expect(sentAt(new Date(2026, 9, 28, 9, 5).toISOString(), now)).toBe("28 Oct 09:05");
  });
});

describe("linking values and pages", () => {
  it("places each value on its page by its index in the document", () => {
    const document = readDocument();

    expect(valuesOnPage(document, 1).map(({ index }) => index)).toEqual([0, 1]);
    expect(valuesOnPage(document, 2)).toEqual([{ index: 2, bbox: [0.3, 0.3, 0.4, 0.4] }]);
    expect(pageOf(document, 2)).toBe(2);
  });

  it("leaves out a value without a usable box", () => {
    const document = readDocument();
    document.values![0]!.bbox = "somewhere";

    expect(valuesOnPage(document, 1).map(({ index }) => index)).toEqual([1]);
  });
});

describe("finding a request", () => {
  it("opens the newest finished drawing first", () => {
    const working = record({ request_id: "r2", items: [item({ status: "reading" })] });

    expect(firstItem([working, record()])).toEqual({ requestId: "r1", itemId: "ctc" });
    expect(firstItem([working])).toEqual({ requestId: "r2", itemId: "ctc" });
    expect(firstItem([])).toBeNull();
  });

  it("matches a typed id exactly, or by the one id it starts", () => {
    const requests = [record({ request_id: "9dd89340aa" }), record({ request_id: "9dd8b111cc" })];

    expect(matchRequest(" 9DD89340AA ", requests)).toBe("9dd89340aa");
    expect(matchRequest("9dd893", requests)).toBe("9dd89340aa");
    expect(matchRequest("9dd8", requests)).toBeNull();
    expect(matchRequest("", requests)).toBeNull();
  });
});

describe("the trace", () => {
  it("joins each router layer's verdict to the routing step of its item", () => {
    const steps = traceSteps(trace("r1").events);

    expect(steps.map((step) => step.event.step)).toEqual([
      "requests.receive",
      "uploads.save",
      "router.route",
      "drawings.read",
    ]);
    expect(steps.map((step) => step.item)).toEqual([null, "ctc", "ctc", "ctc"]);
    expect(steps[2]!.layers).toEqual([
      {
        layer: "structure",
        decided: false,
        route: null,
        confidence: null,
        reason: "not sure",
        error: null,
        duration_ms: 12,
      },
      {
        layer: "probe",
        decided: true,
        route: "drawing",
        confidence: 0.93,
        reason: "the probe gives drawing 0.93",
        error: null,
        duration_ms: 230,
      },
    ]);
  });

  it("still shows the layers of an item whose routing has not ended", () => {
    const layer = event({ step: "route.vlm", output: { decided: false }, error: "Timeout: slow" });

    const steps = traceSteps([event(), layer]);

    expect(steps).toHaveLength(2);
    expect(steps[1]!.event).toBe(layer);
    expect(steps[1]!.layers[0]).toMatchObject({ layer: "vlm", error: "Timeout: slow" });
  });
});
