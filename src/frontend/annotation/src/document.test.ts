import { describe, expect, it } from "vitest";
import {
  addFeature,
  addValue,
  deleteFeature,
  deleteValue,
  renameFeature,
  updateFeature,
  withDefaults,
} from "./document";
import { ctc01 } from "./test/fixtures";

describe("addValue", () => {
  it("appends a draft value with the next id of the drawing at the drawn box", () => {
    const { document, index } = addValue(ctc01(), 1, [0.1, 0.2, 0.3, 0.4]);

    expect(index).toBe(17);
    expect(document.values[17]).toMatchObject({
      id: "ctc01-18",
      page: 1,
      bbox: [0.1, 0.2, 0.3, 0.4],
      unit: "mm",
      status: "draft",
    });
  });

  it("starts at 01 on a drawing with no values yet", () => {
    const empty = { ...ctc01(), drawing: "nist_ftc_06_asme1_rd", page_count: 3, values: [] };
    expect(addValue(empty, 2, [0.1, 0.2, 0.3, 0.4]).document.values[0]!.id).toBe("ftc06-01");
  });
});

describe("features", () => {
  it("adds an empty feature with an unused id on the given page", () => {
    const { document, index } = addFeature(addFeature(ctc01(), 1).document, 1);

    expect(index).toBe(16);
    expect(document.features.slice(15).map((feature) => feature.id)).toEqual([
      "feature_1",
      "feature_2",
    ]);
    expect(document.features[16]).toMatchObject({ type: "other", label: "", page: 1 });
  });

  it("renames a feature and every value that points at it", () => {
    const result = renameFeature(ctc01(), 5, "hole_small");
    if ("taken" in result) throw new Error("rename refused");
    const { document } = result;

    expect(document.features[5]!.id).toBe("hole_small");
    expect(document.values[6]!.feature_id).toBe("hole_small");
    expect(document.values.filter((value) => value.feature_id === "hole_mid")).toEqual([]);
  });

  it("refuses a rename onto another feature's id, which would merge their values", () => {
    expect(renameFeature(ctc01(), 6, "hole_mid")).toEqual({ taken: "hole_mid" });
  });

  it("edits the other feature fields without touching values", () => {
    const document = updateFeature(ctc01(), 5, { label: "small hole" });
    expect(document.features[5]!.label).toBe("small hole");
    expect(document.values).toEqual(ctc01().values);
  });
});

describe("deleting", () => {
  it("refuses to delete a feature that values still point at and names them", () => {
    expect(deleteFeature(ctc01(), 5)).toEqual({ usedBy: ["ctc01-07"] });
  });

  it("deletes an unused feature", () => {
    const { document } = addFeature(ctc01(), 1);
    const result = deleteFeature(document, 15);
    expect("document" in result && result.document.features).toHaveLength(15);
  });

  it("deletes a value", () => {
    const document = deleteValue(ctc01(), 0);
    expect(document.values).toHaveLength(16);
    expect(document.values[0]!.id).toBe("ctc01-02");
  });
});

describe("withDefaults", () => {
  it("fills the fields the schema gives defaults, so a sparse gold file opens", () => {
    const sparse = {
      drawing: "nist_ctc_01_asme1_rd",
      page_count: 1,
      values: [
        { ...ctc01().values[0]!, datums: undefined, status: undefined, applies_to: undefined },
      ],
    };

    const document = withDefaults(sparse);

    expect(document.title_block).toEqual({});
    expect(document.features).toEqual([]);
    expect(document.values[0]).toMatchObject({ datums: [], status: "draft", applies_to: null });
  });

  it("leaves a complete document as it is", () => {
    expect(withDefaults(ctc01())).toEqual(ctc01());
  });
});
