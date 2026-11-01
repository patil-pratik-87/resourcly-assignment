import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { ctc01 } from "./test/fixtures";
import { fakeApi } from "./test/fakeApi";

afterEach(() => {
  vi.restoreAllMocks();
  // The screen keeps the drawing in the address; start every test from a bare one.
  window.history.replaceState(null, "", "/");
});

describe("pin selection", () => {
  it("opens the record of the clicked pin in the form", async () => {
    const user = userEvent.setup();
    render(<App api={fakeApi()} />);

    await user.click(await screen.findByRole("button", { name: "Value 7: ⌀25 ±0.15" }));

    expect(screen.getByLabelText("Raw text")).toHaveValue("⌀25 ±0.15");
    expect(screen.getByLabelText("Feature")).toHaveValue("hole_mid");
  });

  it("steps to the next and previous record with J and K", async () => {
    const user = userEvent.setup();
    render(<App api={fakeApi()} />);
    await user.click(await screen.findByRole("button", { name: "Value 7: ⌀25 ±0.15" }));

    await user.keyboard("j");
    expect(screen.getByLabelText("Raw text")).toHaveValue("⌀34.8 - 35.2");
    await user.keyboard("kk");
    expect(screen.getByLabelText("Raw text")).toHaveValue("⌓ 0.5 | A");
  });

  it("does not step while the person types in a field", async () => {
    const user = userEvent.setup();
    render(<App api={fakeApi()} />);
    await user.click(await screen.findByRole("button", { name: "Value 7: ⌀25 ±0.15" }));

    await user.type(screen.getByLabelText("Raw text"), "j");
    expect(screen.getByLabelText("Raw text")).toHaveValue("⌀25 ±0.15j");
  });
});

describe("drawing on the page", () => {
  /** jsdom has no layout, so give every element a 1000 x 1000 box at the origin. */
  function pageLayout() {
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue(
      DOMRect.fromRect({ x: 0, y: 0, width: 1000, height: 1000 }),
    );
  }

  function pageOverlay(): Element {
    return screen.getByRole("img", { name: /Page 1/ }).nextElementSibling!;
  }

  function drag(from: Element, start: [number, number], end: [number, number]) {
    const at = ([clientX, clientY]: [number, number]) => ({ clientX, clientY, pointerId: 1 });
    fireEvent.pointerDown(from, at(start));
    fireEvent.pointerMove(from, at([(start[0] + end[0]) / 2, (start[1] + end[1]) / 2]));
    fireEvent.pointerMove(from, at(end));
    fireEvent.pointerUp(from, at(end));
  }

  it("draws a new box across an unselected box instead of moving it", async () => {
    pageLayout();
    const user = userEvent.setup();
    render(<App api={fakeApi()} />);
    await user.click(await screen.findByRole("button", { name: "Value 7: ⌀25 ±0.15" }));

    // Value 6's box starts at (674, 376) on the 1000 x 1000 page.
    drag(screen.getByRole("button", { name: "Value 6: ⌓ 0.5 | A" }), [680, 380], [730, 420]);

    expect(screen.getByText(/of 18/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Value 6: ⌓ 0.5 | A" }));
    expect(screen.getByLabelText("Box")).toHaveTextContent("0.674 0.376 0.740 0.430");
  });

  it("places a box for a selected value that has none", async () => {
    pageLayout();
    const user = userEvent.setup();
    const document = ctc01();
    delete (document.values[6] as Partial<(typeof document.values)[number]>).bbox;
    render(<App api={{ ...fakeApi(), document: async () => structuredClone(document) }} />);
    await user.click(await screen.findByRole("button", { name: "Value 6: ⌓ 0.5 | A" }));
    await user.keyboard("j");

    drag(pageOverlay(), [100, 100], [200, 150]);

    expect(screen.getByText(/of 17/)).toBeInTheDocument();
    expect(screen.getByLabelText("Box")).toHaveTextContent("0.100 0.100 0.200 0.150");
  });

  it("pans with Space held even after a pin took the focus", async () => {
    pageLayout();
    const user = userEvent.setup();
    render(<App api={fakeApi()} />);
    await user.click(await screen.findByRole("button", { name: "Value 7: ⌀25 ±0.15" }));
    expect(screen.getByRole("button", { name: "Value 7: ⌀25 ±0.15" })).toHaveFocus();

    fireEvent.keyDown(document.activeElement!, { code: "Space", key: " " });
    drag(pageOverlay(), [100, 100], [200, 150]);
    fireEvent.keyUp(document.activeElement!, { code: "Space", key: " " });

    expect(screen.getByText(/of 17/)).toBeInTheDocument();
  });

  it("still moves the selected box", async () => {
    pageLayout();
    const user = userEvent.setup();
    render(<App api={fakeApi()} />);
    await user.click(await screen.findByRole("button", { name: "Value 7: ⌀25 ±0.15" }));

    drag(screen.getByRole("button", { name: "Value 7: ⌀25 ±0.15" }), [740, 430], [750, 440]);

    expect(screen.getByLabelText("Box")).toHaveTextContent("0.747 0.438 0.799 0.483");
  });
});

describe("multi-page drawings", () => {
  it("follows a value to the page it is moved to", async () => {
    const user = userEvent.setup();
    const api = fakeApi();
    const document = await api.document("nist_ctc_01_asme1_rd");
    render(<App api={{ ...api, document: async () => ({ ...document, page_count: 2 }) }} />);
    await user.click(await screen.findByRole("button", { name: "Value 7: ⌀25 ±0.15" }));

    await user.selectOptions(screen.getByLabelText("Page"), "2");

    expect(screen.getByText("Page 2 of 2")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Value 7: ⌀25 ±0.15" })).toBeInTheDocument();
  });
});

describe("save and validation display", () => {
  async function openValue7(api = fakeApi()) {
    const user = userEvent.setup();
    render(<App api={api} />);
    await user.click(await screen.findByRole("button", { name: "Value 7: ⌀25 ±0.15" }));
    return { user, api };
  }

  it("saves the whole document with the edit in it", async () => {
    const { user, api } = await openValue7();

    await user.type(screen.getByLabelText("Raw text"), " (2x)");
    await user.click(screen.getByRole("button", { name: "Save" }));

    const expected = ctc01();
    expected.values[6]!.raw = "⌀25 ±0.15 (2x)";
    expect(api.saved).toEqual([expected]);
  });

  it("shows the issues of a rejected save next to the field they name", async () => {
    const message =
      "'flatness' is not a dimension kind; use one of: diameter, radius, linear, angular";
    const { user } = await openValue7(
      fakeApi({
        save: async () => ({ ok: false, issues: [{ loc: ["values", 6, "kind"], message }] }),
      }),
    );

    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByLabelText("Kind")).toHaveAccessibleDescription(message);
  });

  it("shows a limits issue under both limit fields, since the API names only limits", async () => {
    const message = "lower must not exceed upper";
    const { user } = await openValue7(
      fakeApi({
        save: async () => ({ ok: false, issues: [{ loc: ["values", 6, "limits"], message }] }),
      }),
    );

    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByLabelText("Lower limit")).toHaveAccessibleDescription(message);
    expect(screen.getByLabelText("Upper limit")).toHaveAccessibleDescription(message);
  });

  it("keeps the edits and says why when the save fails outright", async () => {
    const { user } = await openValue7(
      fakeApi({
        save: async () => {
          throw new Error("cannot open nist_ctc_01_asme1_rd.pdf");
        },
      }),
    );
    await user.type(screen.getByLabelText("Raw text"), "!");

    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(
      await screen.findByText("Not saved: cannot open nist_ctc_01_asme1_rd.pdf"),
    ).toBeVisible();
    expect(screen.getByLabelText("Raw text")).toHaveValue("⌀25 ±0.15!");
  });

  it("shows what the live check finds while the person edits", async () => {
    const check = async (_drawing: string, document: { values: { raw: string }[] }) =>
      document.values[6]!.raw === ""
        ? [{ loc: ["values", 6, "raw"], message: "must not be empty" }]
        : [];
    const { user } = await openValue7(fakeApi({ check }));

    await user.clear(screen.getByLabelText("Raw text"));

    await waitFor(() =>
      expect(screen.getByLabelText("Raw text")).toHaveAccessibleDescription("must not be empty"),
    );
    expect(screen.getByRole("button", { name: "Value 7:" })).toHaveAttribute(
      "title",
      "ctc01-07 (has issues)",
    );
    expect(screen.getByText("has issues")).toBeInTheDocument();
  });
});

describe("unsaved changes", () => {
  it("asks before switching drawing and stays when the person cancels", async () => {
    const user = userEvent.setup();
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    render(<App api={fakeApi()} />);
    await user.click(await screen.findByRole("button", { name: "Value 7: ⌀25 ±0.15" }));
    await user.type(screen.getByLabelText("Raw text"), "!");

    await user.selectOptions(screen.getByLabelText("Drawing"), "nist_ftc_06_asme1_rd");

    expect(confirm).toHaveBeenCalledWith("Discard the unsaved changes to nist_ctc_01_asme1_rd?");
    expect(screen.getByLabelText("Drawing")).toHaveValue("nist_ctc_01_asme1_rd");
    expect(screen.getByLabelText("Raw text")).toHaveValue("⌀25 ±0.15!");
  });

  it("switches without asking when nothing changed", async () => {
    const user = userEvent.setup();
    const confirm = vi.spyOn(window, "confirm");
    render(<App api={fakeApi()} />);
    await screen.findByRole("button", { name: "Value 7: ⌀25 ±0.15" });

    await user.selectOptions(screen.getByLabelText("Drawing"), "nist_ftc_06_asme1_rd");

    expect(await screen.findByText(/No values on this drawing yet/)).toBeInTheDocument();
    expect(confirm).not.toHaveBeenCalled();
  });
});

describe("feature ids", () => {
  async function openFeatures() {
    const user = userEvent.setup();
    const api = fakeApi();
    render(<App api={api} />);
    await screen.findByRole("button", { name: "Value 7: ⌀25 ±0.15" });
    await user.click(screen.getByRole("tab", { name: /Features/ }));
    return { user, api };
  }

  it("renames on leaving the field, even when the typing passes through a taken id", async () => {
    const { user, api } = await openFeatures();
    const id = screen.getByLabelText("Feature 7 id");

    await user.clear(id);
    await user.type(id, "hole_mid_right");
    await user.tab();
    await user.click(screen.getByRole("button", { name: "Save" }));

    const saved = api.saved[0]!;
    expect(saved.features[6]!.id).toBe("hole_mid_right");
    expect(saved.values.find((value) => value.id === "ctc01-08")!.feature_id).toBe(
      "hole_mid_right",
    );
    expect(saved.values.find((value) => value.id === "ctc01-07")!.feature_id).toBe("hole_mid");
  });

  it("refuses an id another feature has and says so", async () => {
    const { user, api } = await openFeatures();
    const id = screen.getByLabelText("Feature 7 id");

    await user.clear(id);
    await user.type(id, "hole_mid");
    await user.tab();

    expect(id).toHaveAccessibleDescription("hole_mid is already a feature id");
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(api.saved[0]!.features[6]!.id).toBe("hole_right");
    expect(api.saved[0]!.values.find((value) => value.id === "ctc01-08")!.feature_id).toBe(
      "hole_right",
    );
  });
});

describe("datum tags", () => {
  async function openValue7WithDatums(datums: string[]) {
    const user = userEvent.setup();
    const api = fakeApi();
    const document = ctc01();
    document.values[6]!.datums = datums;
    render(<App api={{ ...api, document: async () => structuredClone(document) }} />);
    await user.click(await screen.findByRole("button", { name: "Value 7: ⌀25 ±0.15" }));
    return { user, api };
  }

  it("removes only the clicked one of two equal datums", async () => {
    const { user, api } = await openValue7WithDatums(["A", "A", "B"]);

    await user.click(screen.getAllByRole("button", { name: "Remove datum A" })[0]!);
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(api.saved[0]!.values[6]!.datums).toEqual(["A", "B"]);
  });

  it("splits a pasted comma list into one tag per datum", async () => {
    const { user, api } = await openValue7WithDatums([]);

    await user.click(screen.getByLabelText("Datums"));
    await user.paste("A, B, C");
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(api.saved[0]!.values[6]!.datums).toEqual(["A", "B", "C"]);
  });
});

describe("the address", () => {
  it("keeps the open drawing in the hash, encoded so a reload finds it again", async () => {
    const api = fakeApi();
    const odd = { ...ctc01(), drawing: "odd name#1%" };
    render(
      <App
        api={{
          ...api,
          drawings: async () => [{ ...(await api.drawings())[0]!, drawing: odd.drawing }],
          document: async () => structuredClone(odd),
        }}
      />,
    );

    await screen.findByRole("button", { name: "Value 7: ⌀25 ±0.15" });

    expect(window.location.hash).toBe("#odd%20name%231%25");
    expect(decodeURIComponent(window.location.hash.slice(1))).toBe("odd name#1%");
  });
});

describe("the opened drawing", () => {
  it("saves to the drawing that was opened even when the file names another", async () => {
    const user = userEvent.setup();
    const api = fakeApi();
    const misnamed = { ...ctc01(), drawing: "nist_ftc_06_asme1_rd" };
    render(<App api={{ ...api, document: async () => structuredClone(misnamed) }} />);
    await screen.findByRole("button", { name: "Value 7: ⌀25 ±0.15" });

    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(api.savedTo).toEqual(["nist_ctc_01_asme1_rd"]);
    expect(screen.getByRole("img", { name: /Page 1/ })).toHaveAttribute(
      "src",
      "/pages/nist_ctc_01_asme1_rd/1.png",
    );
  });
});

describe("stored values outside the schema", () => {
  function openWith(edit: (document: ReturnType<typeof ctc01>) => void) {
    const api = fakeApi();
    const document = ctc01();
    edit(document);
    render(<App api={{ ...api, document: async () => structuredClone(document) }} />);
    return api;
  }

  it("shows enum values the schema does not list as stored instead of crashing", async () => {
    const user = userEvent.setup();
    openWith((document) => {
      Object.assign(document.values[6]!, { callout: "leader", tolerance_style: "odd", unit: "cm" });
      Object.assign(document.features[5]!, { type: "groove" });
    });

    await user.click(await screen.findByRole("button", { name: "Value 7: ⌀25 ±0.15" }));

    expect(screen.getByLabelText("Callout")).toHaveValue("leader");
    expect(screen.getByLabelText("Kind")).toHaveValue("diameter");
    expect(screen.getByLabelText("Tolerance style")).toHaveValue("odd");
    expect(screen.getByLabelText("Unit")).toHaveValue("cm");
    await user.click(screen.getByRole("tab", { name: /Features/ }));
    expect(screen.getByLabelText("Feature 6 type")).toHaveValue("groove");
  });

  it("opens a value that has no kind or box, so the person can fix it", async () => {
    const user = userEvent.setup();
    openWith((document) => {
      const value = document.values[6] as Partial<(typeof document.values)[number]>;
      delete value.kind;
      delete value.bbox;
    });

    await user.click(await screen.findByRole("button", { name: "Value 6: ⌓ 0.5 | A" }));
    await user.keyboard("j");

    expect(screen.getByLabelText("Raw text")).toHaveValue("⌀25 ±0.15");
    expect(screen.getByLabelText("Kind")).toHaveValue("");
    expect(screen.getByLabelText("Box")).toHaveTextContent("none");
    expect(screen.queryByRole("button", { name: "Value 7: ⌀25 ±0.15" })).toBeNull();
  });
});

describe("saving twice quickly", () => {
  it("sends one save while one is in flight and ends saved", async () => {
    const user = userEvent.setup();
    const pending: (() => void)[] = [];
    const api = fakeApi();
    const save: typeof api.save = (drawing, document) =>
      new Promise((resolve) => pending.push(() => resolve(api.save(drawing, { ...document }))));
    render(<App api={{ ...api, save }} />);
    await user.click(await screen.findByRole("button", { name: "Value 7: ⌀25 ±0.15" }));
    await user.type(screen.getByLabelText("Raw text"), "!");

    await user.keyboard("{Control>}s{/Control}{Control>}s{/Control}");
    pending.forEach((finish) => finish());

    await waitFor(() => expect(screen.getByText("Saved")).toBeInTheDocument());
    expect(pending).toHaveLength(1);
    expect(screen.queryByText("Unsaved changes")).toBeNull();
  });
});

describe("shortcuts with a select focused", () => {
  it("approves with A instead of jumping the select to an option", async () => {
    const user = userEvent.setup();
    render(<App api={fakeApi()} />);
    await user.click(await screen.findByRole("button", { name: "Value 7: ⌀25 ±0.15" }));
    screen.getByLabelText("Kind").focus();

    await user.keyboard("a");

    expect(screen.getByLabelText("Counts")).toHaveTextContent("1 approved");
    expect(screen.getByText(/Value 8/)).toBeInTheDocument();
  });
});

describe("issues on fields without a control", () => {
  it("shows them, and lets the person remove a field the schema does not have", async () => {
    const user = userEvent.setup();
    const document = ctc01();
    Object.assign(document.values[6]!, { note: "check this" });
    Object.assign(document.title_block, { owner: "NIST" });
    const issues = [
      { loc: ["values", 6, "status"], message: "must be 'draft' or 'approved'" },
      { loc: ["values", 6, "note"], message: "is not a field in the schema" },
      { loc: ["title_block", "owner"], message: "is not a field in the schema" },
      { loc: ["page_count"], message: "the PDF has 1 page(s)" },
    ];
    const api = fakeApi({ check: async () => issues });
    render(<App api={{ ...api, document: async () => structuredClone(document) }} />);
    await user.click(await screen.findByRole("button", { name: "Value 7: ⌀25 ±0.15" }));

    expect(await screen.findByText("status: must be 'draft' or 'approved'")).toBeVisible();
    expect(screen.getByText("note: is not a field in the schema")).toBeVisible();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "title_block.owner: is not a field in the schema",
    );
    expect(screen.getByRole("alert")).toHaveTextContent("page_count: the PDF has 1 page(s)");

    await user.click(screen.getByRole("button", { name: "Remove note" }));
    await user.click(screen.getByRole("button", { name: "Remove title_block.owner" }));
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(api.saved[0]!.values[6]).not.toHaveProperty("note");
    expect(api.saved[0]!.title_block).not.toHaveProperty("owner");
  });
});

describe("page coverage", () => {
  it("says when the page shown is outside page_coverage", async () => {
    const user = userEvent.setup();
    const document = { ...ctc01(), page_count: 2, page_coverage: [2] };
    document.values.forEach((value) => (value.page = 2));
    render(<App api={{ ...fakeApi(), document: async () => structuredClone(document) }} />);

    const pages = await screen.findByRole("navigation", { name: "Pages" });
    expect(pages).toHaveTextContent("Page 1 of 2 (not labelled)");
    await user.click(screen.getByRole("button", { name: "Next page" }));
    expect(pages).toHaveTextContent(/^‹Page 2 of 2›$/);
  });

  it("treats page_coverage as a schema field: shown with its issue, never offered for removal", async () => {
    const user = userEvent.setup();
    const document = { ...ctc01(), page_count: 2, page_coverage: [2, 1] };
    const message = "must list pages in ascending order, each once";
    const api = fakeApi({ check: async () => [{ loc: ["page_coverage"], message }] });
    render(<App api={{ ...api, document: async () => structuredClone(document) }} />);

    expect(await screen.findByRole("alert")).toHaveTextContent(`page_coverage: ${message}`);
    expect(screen.queryByRole("button", { name: "Remove page_coverage" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(api.saved[0]!.page_coverage).toEqual([2, 1]);
  });
});

describe("a drawing that fails to open", () => {
  it("still offers the drawing picker when the first drawing cannot be opened", async () => {
    const user = userEvent.setup();
    const api = fakeApi();
    const document: typeof api.document = async (drawing) => {
      if (drawing === "nist_ctc_01_asme1_rd") throw new Error("cannot open the PDF");
      return api.document(drawing);
    };
    render(<App api={{ ...api, document }} />);

    expect(
      await screen.findByText(/Could not open nist_ctc_01_asme1_rd: cannot open the PDF/),
    ).toBeVisible();
    await user.selectOptions(screen.getByLabelText("Drawing"), "nist_ftc_06_asme1_rd");

    expect(await screen.findByText(/No values on this drawing yet/)).toBeInTheDocument();
  });
});
