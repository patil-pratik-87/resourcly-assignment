import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import App from "./App";
import { createAgentApi } from "./api";
import { event, fakeAgentApi, item, record, routing } from "./test/fakeAgentApi";

afterEach(() => {
  window.history.replaceState(null, "", "/");
});

function open(path: string) {
  window.history.replaceState(null, "", path);
}

const pdf = (name: string) => new File(["%PDF-1.7"], name, { type: "application/pdf" });

describe("sending files from the chat", () => {
  it("sends the text and every attached file as one request", async () => {
    open("/");
    const user = userEvent.setup();
    const { api, state } = fakeAgentApi();
    render(<App api={api} />);

    await user.upload(screen.getByTestId("file-picker"), [pdf("a.pdf"), pdf("b.pdf")]);
    await user.click(screen.getByRole("button", { name: "Remove b.pdf" }));
    await user.upload(screen.getByTestId("file-picker"), pdf("c.pdf"));
    await user.type(screen.getByLabelText("Message"), "read these{Enter}");

    expect(state.sent).toHaveLength(1);
    expect(state.sent[0]!.text).toBe("read these");
    expect(state.sent[0]!.files.map((file) => file.name)).toEqual(["a.pdf", "c.pdf"]);
    expect(await screen.findByRole("region", { name: "a.pdf" })).toHaveTextContent(
      "Choosing the case",
    );
    expect(screen.queryByRole("button", { name: "Remove a.pdf" })).not.toBeInTheDocument();
  });

  it("attaches files dropped anywhere on the chat", async () => {
    open("/chat");
    const { api } = fakeAgentApi();
    render(<App api={api} />);
    const files = [pdf("dropped.pdf")];
    const dataTransfer = { types: ["Files"], files };

    fireEvent.dragEnter(window, { dataTransfer });
    expect(await screen.findByText("Drop to attach")).toBeInTheDocument();
    fireEvent.drop(window, { dataTransfer });

    expect(await screen.findByText("dropped.pdf")).toBeInTheDocument();
    expect(screen.queryByText("Drop to attach")).not.toBeInTheDocument();
  });

  it("holds back a file over the size cap and says why", async () => {
    open("/chat");
    const user = userEvent.setup();
    const { api, state } = fakeAgentApi();
    render(<App api={api} />);
    const huge = new File(["%PDF"], "huge.pdf", { type: "application/pdf" });
    Object.defineProperty(huge, "size", { value: 30 * 1024 * 1024 });

    await user.upload(screen.getByTestId("file-picker"), huge);
    await screen.findByText("Router");
    await user.click(screen.getByRole("button", { name: "Send" }));

    expect(state.sent).toHaveLength(0);
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Not sent: huge.pdf is 30.0 MB; each file can be at most 25 MB.",
    );
    expect(screen.getByText("huge.pdf")).toBeInTheDocument();
  });

  it("says plainly when the server cannot be reached, and keeps the message", async () => {
    open("/chat");
    const user = userEvent.setup();
    // Reads still answer; the send finds nothing listening.
    const api = createAgentApi(async (url, init) => {
      if (init?.method === "POST") throw new TypeError("Failed to fetch");
      if (url === "/api/agent") return Response.json({ reader: "r", router: "s" });
      return Response.json([]);
    });
    render(<App api={api} />);

    await user.type(screen.getByLabelText("Message"), "anyone there?{Enter}");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Not sent: The server could not be reached",
    );
    expect(screen.getByLabelText("Message")).toHaveValue("anyone there?");
  });

  it("does not send an empty message", async () => {
    open("/chat");
    const { api } = fakeAgentApi();
    render(<App api={api} />);

    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
  });
});

describe("the agent's answer for each item", () => {
  it("shows the case, the live read and then the result as the agent works", async () => {
    open("/chat");
    const user = userEvent.setup();
    const { api, state } = fakeAgentApi();
    render(<App api={api} />);
    await user.upload(screen.getByTestId("file-picker"), pdf("ctc.pdf"));
    await user.click(screen.getByRole("button", { name: "Send" }));

    const reading = item({
      name: "ctc.pdf",
      status: "reading",
      values: null,
      progress: {
        page: 1,
        pages: 1,
        done: 2,
        total: 5,
        boxes: [
          [0, 0, 0.1, 0.1],
          [0.2, 0.2, 0.3, 0.3],
          [0.4, 0.4, 0.5, 0.5],
        ],
        page_done: 2,
        latest: ["⌀25 ±0.15"],
      },
    });
    state.requests = [record({ request_id: "new", status: "working", items: [reading] })];
    const card = await screen.findByRole("region", { name: "ctc.pdf" }, { timeout: 3000 });
    await waitFor(() => expect(card).toHaveTextContent("Reading callout 3 of 5"), {
      timeout: 3000,
    });
    expect(card).toHaveTextContent("Technical drawing");
    expect(card).toHaveTextContent("Chosen by the stand-in rule.");
    expect(card).toHaveTextContent("Just read⌀25 ±0.15");
    expect(card).toHaveTextContent("70% sure");
    expect(within(card).getByRole("progressbar")).toHaveAttribute("aria-valuenow", "40");
    // The page shows the callouts found so far: two read, one being read.
    expect(card.querySelectorAll(".mark.read")).toHaveLength(2);
    expect(card.querySelectorAll(".mark.now")).toHaveLength(1);

    state.requests = [record({ request_id: "new", items: [item({ name: "ctc.pdf" })] })];
    await waitFor(() => expect(card).toHaveTextContent("3 values read"), { timeout: 3000 });
    // Done, the page shows a box for each value the reader placed on it.
    await waitFor(() => expect(card.querySelectorAll(".mark.read")).toHaveLength(2));
    expect(within(card).getByRole("link", { name: "Download JSON" })).toHaveAttribute(
      "href",
      "/download/new/ctc",
    );
  });

  it("shows a drawing's JSON in the chat", async () => {
    open("/chat");
    const user = userEvent.setup();
    const { api } = fakeAgentApi([record()]);
    render(<App api={api} />);

    const card = await screen.findByRole("region", { name: "ctc.pdf" });
    await user.click(within(card).getByRole("button", { name: "Show JSON" }));

    const json = await within(card).findByRole("region", { name: "JSON of ctc.pdf" });
    expect(json).toHaveTextContent('"raw": "⌀20 ±0.1"');
    expect(json).toHaveTextContent("3 values");
    await user.click(within(card).getByRole("button", { name: "Hide JSON" }));
    expect(within(card).queryByRole("region", { name: "JSON of ctc.pdf" })).toBeNull();
  });

  it("answers a photo as a reply, without a result to download", async () => {
    open("/chat");
    const photo = item({
      item_id: "crack",
      name: "crack.jpg",
      media_type: "image/jpeg",
      status: "answered",
      values: null,
      route: routing({
        route: "photo",
        confidence: 0.6,
        reason: "An image is taken as a photo of a part.",
      }),
      reply: "Saying what is wrong with it and what to do is not available yet.",
    });
    const { api } = fakeAgentApi([record({ items: [photo] })]);
    render(<App api={api} />);

    const card = await screen.findByRole("region", { name: "crack.jpg" });
    expect(card).toHaveTextContent("Photo of a part");
    expect(card).toHaveTextContent("60% sure");
    expect(within(card).getByRole("note")).toHaveTextContent("not available yet");
    expect(within(card).queryByRole("link", { name: "Download JSON" })).not.toBeInTheDocument();
    const preview = within(card).getByRole("button", { name: "Open crack.jpg in the viewer" });
    expect(within(preview).getByRole("presentation")).toHaveAttribute(
      "src",
      "/pages/r1/crack/1.png",
    );
  });

  it("answers a message without files as a text question", async () => {
    open("/chat");
    const question = item({
      item_id: "message",
      kind: "text",
      name: "why did the bracket crack?",
      media_type: null,
      size: 0,
      status: "answered",
      values: null,
      route: routing({ route: "text", confidence: 1, reason: "A message without a file is text." }),
      reply: "Answering questions from the NTSB reports is not available yet.",
    });
    const { api } = fakeAgentApi([
      record({ text: "why did the bracket crack?", items: [question] }),
    ]);
    render(<App api={api} />);

    const card = await screen.findByRole("region", { name: "Your message" });
    expect(card).toHaveTextContent("Text question");
    expect(within(card).getByRole("note")).toHaveTextContent("not available yet");
  });

  it("shows a routing no layer was sure of without a confidence", async () => {
    open("/chat");
    const unsure = item({
      item_id: "scan",
      name: "scan.pdf",
      status: "answered",
      values: null,
      route: routing({
        route: "other",
        layer: "none",
        confidence: null,
        reason: "no layer was sure",
      }),
      reply: "This fits neither case the agent handles.",
    });
    const { api } = fakeAgentApi([record({ items: [unsure] })]);
    render(<App api={api} />);

    const card = await screen.findByRole("region", { name: "scan.pdf" });
    expect(card).toHaveTextContent("Fits no case");
    expect(card).toHaveTextContent("Chosen by no layer, none was sure.");
    expect(card).not.toHaveTextContent("% sure");
  });

  it("counts the items of a bulk upload by state", async () => {
    open("/chat");
    const items = [
      item({ item_id: "a", name: "a.pdf" }),
      item({ item_id: "b", name: "b.pdf", status: "queued", values: null }),
      item({ item_id: "c", name: "c.jpg", status: "answered", reply: "Not available yet." }),
    ];
    const { api } = fakeAgentApi([record({ status: "working", items })]);
    render(<App api={api} />);

    const request = await screen.findByRole("article", { name: "Request r1" });
    expect(within(request).getByRole("status", { name: "Progress" })).toHaveTextContent(
      "3 files: 1 read, 1 answered, 1 in progress",
    );
    expect(within(request).getAllByRole("region")).toHaveLength(3);
  });

  it.each([
    [8, ["d0.pdf", "d1.pdf", "d2.pdf", "d3.pdf", "d4.pdf", "d5.pdf", "and 2 more files"]],
    [7, ["d0.pdf", "d1.pdf", "d2.pdf", "d3.pdf", "d4.pdf", "d5.pdf", "d6.pdf"]],
  ])("names the first files of an upload of %i and counts the rest", async (count, shown) => {
    open("/chat");
    const items = Array.from({ length: count }, (_, n) =>
      item({ item_id: `d${n}`, name: `d${n}.pdf` }),
    );
    const { api } = fakeAgentApi([record({ items })]);
    render(<App api={api} />);

    const request = await screen.findByRole("article", { name: "Request r1" });
    const sent = within(request).getAllByRole("list")[0]!;
    expect(
      within(sent)
        .getAllByRole("listitem")
        .map((li) => li.textContent),
    ).toEqual(shown);
  });
});

describe("the page and its JSON, linked", () => {
  const scrolled: Element[] = [];

  beforeEach(() => {
    scrolled.length = 0;
    window.localStorage.clear();
    // jsdom has no layout, so record what the screen asks to bring into view.
    Element.prototype.scrollIntoView = function (this: Element) {
      scrolled.push(this);
    };
  });

  afterEach(() => {
    delete (Element.prototype as Partial<Element>).scrollIntoView;
  });

  async function viewer(path = "/requests/r1/ctc", requests = [record()]) {
    open(path);
    const user = userEvent.setup();
    const fake = fakeAgentApi(requests);
    render(<App api={fake.api} />);
    await screen.findByRole("button", { name: "JSON of value 1" });
    return { user, ...fake };
  }

  it("shows the page of the upload with a numbered box for each value on it", async () => {
    await viewer();

    const page = screen.getByRole("region", { name: "Page" });
    expect(within(page).getByRole("heading", { name: "ctc.pdf" })).toBeInTheDocument();
    expect(within(page).getByRole("img", { name: "Page 1 of ctc.pdf" })).toHaveAttribute(
      "src",
      "/pages/r1/ctc/1.png",
    );
    expect(within(page).getByRole("button", { name: "Value 1: ⌀10 ±0.1" })).toHaveTextContent("1");
    expect(within(page).getByRole("button", { name: "Value 2: ⌀20 ±0.1" })).toHaveTextContent("2");
    expect(page).toHaveTextContent("2 values on this page");
    const side = screen.getByRole("complementary", { name: "What the agent did" });
    expect(side).toHaveTextContent("Technical drawing");
    expect(side).toHaveTextContent("Chosen by the stand-in rule.");
    expect(within(side).getByRole("link", { name: "Download JSON" })).toHaveAttribute(
      "href",
      "/download/r1/ctc",
    );
  });

  it("highlights the JSON entry of the box under the pointer, and the other way", async () => {
    const { user } = await viewer();
    const box = screen.getByRole("button", { name: "Value 2: ⌀20 ±0.1" });
    const entry = screen.getByRole("button", { name: "JSON of value 2" });

    await user.hover(box);
    expect(entry).toHaveClass("hovered");

    await user.hover(screen.getByRole("button", { name: "JSON of value 1" }));
    expect(screen.getByRole("button", { name: "Value 1: ⌀10 ±0.1" })).toHaveClass("hovered");
    expect(box).not.toHaveClass("hovered");
  });

  it("scrolls the JSON to the value of a clicked box", async () => {
    const { user } = await viewer();

    await user.click(screen.getByRole("button", { name: "Value 2: ⌀20 ±0.1" }));

    const entry = screen.getByRole("button", { name: "JSON of value 2" });
    expect(entry).toHaveAttribute("aria-pressed", "true");
    expect(scrolled).toContain(entry);
    expect(screen.getByText("A diameter of 20 mm.")).toBeInTheDocument();
  });

  it("opens the page of a value chosen in the JSON and brings its box into view", async () => {
    const { user } = await viewer();
    expect(screen.getByText("Page 1 of 2")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "JSON of value 3" }));

    expect(screen.getByText("Page 2 of 2")).toBeInTheDocument();
    const box = await screen.findByRole("button", { name: "Value 3: ⌀30 ±0.1" });
    expect(box).toHaveAttribute("aria-pressed", "true");
    await waitFor(() => expect(scrolled).toContain(box));
  });

  it("steps through the values with J and K", async () => {
    const { user } = await viewer();

    await user.keyboard("jj");
    expect(screen.getByRole("button", { name: "JSON of value 2" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await user.keyboard("j");
    expect(screen.getByText("Page 2 of 2")).toBeInTheDocument();
  });

  it("zooms the page in and out, and back to fit", async () => {
    const { user } = await viewer();
    const zoom = screen.getByRole("group", { name: "Zoom" });
    const level = within(zoom).getByTitle("Fit the page");
    const fit = level.textContent;

    await user.click(within(zoom).getByRole("button", { name: "Zoom in" }));
    expect(level.textContent).not.toBe(fit);
    await user.click(level);
    expect(level.textContent).toBe(fit);
  });

  it("shows the trace of the request beside the page", async () => {
    const { user } = await viewer();

    await user.click(screen.getByRole("tab", { name: "Trace" }));

    const trace = await screen.findByRole("region", { name: "Trace" });
    expect(await within(trace).findByText("router.route")).toBeInTheDocument();
    expect(within(trace).getByText("uv run resourcly request r1")).toBeInTheDocument();
  });

  it("lists each router layer's verdict in the trace", async () => {
    const { user } = await viewer();
    await user.click(screen.getByRole("tab", { name: "Trace" }));

    const layers = await screen.findByRole("list", { name: "Router layers for ctc" });
    const [first, second] = within(layers).getAllByRole("listitem");
    expect(first).toHaveTextContent("structure rules");
    expect(first).toHaveTextContent("Passed on");
    expect(first).toHaveTextContent("Not sure.");
    expect(second).toHaveTextContent("image probe");
    expect(second).toHaveTextContent("Decided Technical drawing");
    expect(second).toHaveTextContent("93%");
    expect(second).toHaveTextContent("The probe gives drawing 0.93.");
  });

  it("shows the open item's steps of a bulk request until asked for them all", async () => {
    const items = [item({ item_id: "a", name: "a.pdf" }), item({ item_id: "b", name: "b.pdf" })];
    const fake = fakeAgentApi([record({ items })]);
    const steps = (...names: [string, string | null][]) =>
      names.map(([step, about]) => event({ step, input: about ? { item: about } : {} }));
    fake.api.trace = async (id) => ({
      request_id: id,
      events: steps(
        ["requests.receive", null],
        ["uploads.save", "a"],
        ["uploads.save", "b"],
        ["router.route", "a"],
        ["router.route", "b"],
      ),
    });
    open("/requests/r1/b");
    const user = userEvent.setup();
    render(<App api={fake.api} />);
    await user.click(await screen.findByRole("tab", { name: "Trace" }));

    const trace = await screen.findByRole("region", { name: "Trace" });
    await within(trace).findByText("requests.receive");
    expect(within(trace).getAllByRole("listitem")).toHaveLength(3);
    expect(within(trace).getAllByText("b")).toHaveLength(2);
    expect(within(trace).queryByText("a")).toBeNull();

    await user.click(within(trace).getByRole("button", { name: "Whole request" }));
    expect(within(trace).getAllByRole("listitem")).toHaveLength(5);
    expect(within(trace).getAllByText("a")).toHaveLength(2);
  });

  it("shows a photo's page and opens it on its trace", async () => {
    const photo = item({
      item_id: "crack",
      name: "crack.jpg",
      media_type: "image/jpeg",
      pages: 1,
      status: "answered",
      values: null,
      route: routing({ route: "photo", confidence: 0.6, reason: "An image is a photo." }),
      reply: "Not available yet.",
    });
    open("/requests/r1/crack");
    render(<App api={fakeAgentApi([record({ items: [photo] })]).api} />);

    expect(await screen.findByRole("img", { name: "Page 1 of crack.jpg" })).toHaveAttribute(
      "src",
      "/pages/r1/crack/1.png",
    );
    expect(screen.queryByRole("tab", { name: "JSON" })).toBeNull();
    expect(await screen.findByRole("region", { name: "Trace" })).toBeInTheDocument();
  });

  it("opens the newest finished drawing when the address names none", async () => {
    await viewer("/requests");

    expect(window.location.pathname).toBe("/requests/r1/ctc");
  });

  it("looks up a request by the start of its id", async () => {
    const other = record({
      request_id: "9dd89340bbf3",
      items: [item({ item_id: "two", name: "two.pdf" })],
    });
    const { user } = await viewer("/requests/r1/ctc", [record(), other]);
    await user.click(screen.getByRole("button", { name: "Show the requests" }));

    await user.type(screen.getByLabelText("Request id"), "9dd8{Enter}");

    expect(await screen.findByRole("heading", { name: "two.pdf" })).toBeInTheDocument();
    expect(window.location.pathname).toBe("/requests/9dd89340bbf3/two");
  });

  it("looks up a request the list no longer holds, and says when there is none", async () => {
    const { user, state } = await viewer();
    state.stored = [record({ request_id: "old", items: [item({ item_id: "o", name: "o.pdf" })] })];
    await user.click(screen.getByRole("button", { name: "Show the requests" }));

    await user.type(screen.getByLabelText("Request id"), "old{Enter}");
    expect(await screen.findByRole("heading", { name: "o.pdf" })).toBeInTheDocument();

    await user.clear(screen.getByLabelText("Request id"));
    await user.type(screen.getByLabelText("Request id"), "nope{Enter}");
    expect(await screen.findByRole("alert")).toHaveTextContent("no request nope");
  });
});

describe("the requests layout", () => {
  beforeEach(() => window.localStorage.clear());

  async function viewer() {
    open("/requests/r1/ctc");
    const user = userEvent.setup();
    const { api } = fakeAgentApi([record()]);
    render(<App api={api} />);
    await screen.findByRole("button", { name: "JSON of value 1" });
    return user;
  }

  it("folds the request list once a file is open, and shows it again on request", async () => {
    const user = await viewer();
    expect(screen.queryByRole("navigation", { name: "Requests" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Show the requests" }));
    expect(screen.getByRole("navigation", { name: "Requests" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Hide the requests" }));
    expect(screen.queryByRole("navigation", { name: "Requests" })).not.toBeInTheDocument();
  });

  it("hands focus to the other toggle after a keyboard fold or unfold", async () => {
    const user = await viewer();
    screen.getByRole("button", { name: "Show the requests" }).focus();
    await user.keyboard("{Enter}");
    expect(screen.getByRole("button", { name: "Hide the requests" })).toHaveFocus();

    await user.keyboard("{Enter}");
    expect(screen.getByRole("button", { name: "Show the requests" })).toHaveFocus();
  });

  it("remembers an unfolded list the next time", async () => {
    const user = await viewer();
    await user.click(screen.getByRole("button", { name: "Show the requests" }));
    cleanup();

    await viewer();
    expect(screen.getByRole("navigation", { name: "Requests" })).toBeInTheDocument();
  });

  it("resizes the side column from the keyboard and remembers it", async () => {
    const user = await viewer();
    const handle = screen.getByRole("separator", { name: "Resize the side column" });
    expect(handle).toHaveAttribute("aria-valuenow", "28");

    handle.focus();
    await user.keyboard("{ArrowLeft}{ArrowLeft}");

    expect(handle).toHaveAttribute("aria-valuenow", "32");
    expect(
      JSON.parse(window.localStorage.getItem("resourcly.requests.layout")!).sideShare,
    ).toBeCloseTo(0.32);
  });
});

describe("addresses", () => {
  it("moves between the chat and the requests without reloading", async () => {
    open("/chat");
    const user = userEvent.setup();
    const { api } = fakeAgentApi([record()]);
    render(<App api={api} />);

    await user.click(await screen.findByRole("button", { name: "Open in viewer" }));
    expect(window.location.pathname).toBe("/requests/r1/ctc");

    act(() => {
      window.history.back();
    });
    await waitFor(() => expect(window.location.pathname).toBe("/chat"));
    expect(await screen.findByRole("region", { name: "ctc.pdf" })).toBeInTheDocument();
  });
});
