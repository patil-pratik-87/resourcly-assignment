import { describe, expect, it } from "vitest";
import { createApi } from "./api";
import { ctc01 } from "./test/fixtures";

/** A fetch that answers one canned response and records the request it got. */
function fakeFetch(status: number, body: unknown) {
  const requests: { url: string; init?: RequestInit }[] = [];
  const fetch = async (url: string, init?: RequestInit) => {
    requests.push({ url, init });
    return new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    });
  };
  return { fetch, requests };
}

describe("api", () => {
  it("saves the whole document with PUT and returns what the server stored", async () => {
    const document = ctc01();
    const { fetch, requests } = fakeFetch(200, document);

    const result = await createApi(fetch).save(document.drawing, document);

    expect(result).toEqual({ ok: true, document });
    expect(requests[0]!.url).toBe("/api/drawings/nist_ctc_01_asme1_rd");
    expect(requests[0]!.init?.method).toBe("PUT");
    expect(JSON.parse(String(requests[0]!.init?.body))).toEqual(document);
  });

  it("returns the field issues when the server rejects a save", async () => {
    const issues = [{ loc: ["values", 3, "kind"], message: "'flatness' is not a dimension kind" }];
    const { fetch } = fakeFetch(422, { detail: "invalid", issues });

    expect(await createApi(fetch).save("nist_ctc_01_asme1_rd", ctc01())).toEqual({
      ok: false,
      issues,
    });
  });

  it("throws the server's detail for any other failure", async () => {
    const { fetch } = fakeFetch(404, { detail: "'x' is not a drawing name" });

    await expect(createApi(fetch).save("nist_ctc_01_asme1_rd", ctc01())).rejects.toThrow(
      "'x' is not a drawing name",
    );
  });

  it("checks a document without saving it", async () => {
    const issues = [{ loc: ["values", 0, "raw"], message: "must not be empty" }];
    const { fetch, requests } = fakeFetch(200, issues);

    expect(await createApi(fetch).check("nist_ctc_01_asme1_rd", ctc01())).toEqual(issues);
    expect(requests[0]!.url).toBe("/api/drawings/nist_ctc_01_asme1_rd/check");
    expect(requests[0]!.init?.method).toBe("POST");
  });

  it("reads the drawing list and one document", async () => {
    const list = fakeFetch(200, [{ drawing: "nist_ctc_01_asme1_rd" }]);
    expect(await createApi(list.fetch).drawings()).toEqual([{ drawing: "nist_ctc_01_asme1_rd" }]);
    expect(list.requests[0]!.url).toBe("/api/drawings");

    const one = fakeFetch(200, ctc01());
    expect(await createApi(one.fetch).document("nist_ctc_01_asme1_rd")).toEqual(ctc01());
    expect(one.requests[0]!.url).toBe("/api/drawings/nist_ctc_01_asme1_rd");
  });

  it("builds the rendered page address", () => {
    expect(createApi(fakeFetch(200, null).fetch).pageImage("nist_ftc_06_asme1_rd", 2)).toBe(
      "/api/drawings/nist_ftc_06_asme1_rd/pages/2.png?dpi=150",
    );
  });

  it("throws when a drawing cannot be read rather than treating the error as a document", async () => {
    const { fetch } = fakeFetch(422, { detail: "cannot open nist_x.pdf" });

    await expect(createApi(fetch).document("nist_x")).rejects.toThrow("cannot open nist_x.pdf");
  });

  it("encodes the drawing id in every path", async () => {
    const { fetch, requests } = fakeFetch(200, []);
    const api = createApi(fetch);
    const odd = { ...ctc01(), drawing: "odd name#1%" };

    await api.document(odd.drawing);
    await api.check(odd.drawing, odd);

    expect(requests.map((request) => request.url)).toEqual([
      "/api/drawings/odd%20name%231%25",
      "/api/drawings/odd%20name%231%25/check",
    ]);
    expect(api.pageImage(odd.drawing, 1)).toBe(
      "/api/drawings/odd%20name%231%25/pages/1.png?dpi=150",
    );
  });

  it("sends to the drawing it is given, not the drawing the document names", async () => {
    const { fetch, requests } = fakeFetch(200, []);
    const api = createApi(fetch);
    const misnamed = { ...ctc01(), drawing: "nist_ftc_06_asme1_rd" };

    await api.check("nist_ctc_01_asme1_rd", misnamed);
    await api.save("nist_ctc_01_asme1_rd", misnamed);

    expect(requests.map((request) => request.url)).toEqual([
      "/api/drawings/nist_ctc_01_asme1_rd/check",
      "/api/drawings/nist_ctc_01_asme1_rd",
    ]);
  });

  it("throws the detail of a 422 save that lists no issues, such as an unreadable drawing", async () => {
    const { fetch } = fakeFetch(422, { detail: "cannot open nist_ctc_01_asme1_rd.pdf" });

    await expect(createApi(fetch).save("nist_ctc_01_asme1_rd", ctc01())).rejects.toThrow(
      "cannot open nist_ctc_01_asme1_rd.pdf",
    );
  });
});
