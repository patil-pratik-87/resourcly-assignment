import { describe, expect, it } from "vitest";
import { addDatum, applyField, formatValue, parseValue } from "./form";
import { ctc01 } from "./test/fixtures";

describe("parseValue", () => {
  it("reads a single number", () => {
    expect(parseValue("25")).toBe(25);
    expect(parseValue("-0.15")).toBe(-0.15);
  });
});

describe("parseValue ranges and blanks", () => {
  it("reads a range typed with or without brackets", () => {
    expect(parseValue("[34.8, 35.2]")).toEqual([34.8, 35.2]);
    expect(parseValue("34.8, 35.2")).toEqual([34.8, 35.2]);
  });

  it("reads an empty field as no value", () => {
    expect(parseValue("  ")).toBeNull();
  });

  it("keeps text that is not a number so the API can name the field", () => {
    expect(parseValue("abc")).toBe("abc");
    expect(parseValue("1,")).toBe("1,");
  });
});

describe("formatValue", () => {
  it("writes a range in brackets and no value as blank", () => {
    expect(formatValue([34.8, 35.2])).toBe("[34.8, 35.2]");
    expect(formatValue(null)).toBe("");
    expect(formatValue(25)).toBe("25");
  });

  it("round-trips every value in the CTC-01 gold document", () => {
    for (const value of ctc01().values) {
      expect(parseValue(formatValue(value.value))).toEqual(value.value);
    }
  });
});

describe("applyField", () => {
  // ctc01-07: the 25 mm diameter of hole_mid, plus or minus 0.15.
  const hole = () => ctc01().values[6]!;

  it("stores a cleared optional field as null", () => {
    expect(applyField(hole(), "feature_id", "").feature_id).toBeNull();
    expect(applyField(hole(), "unit", "").unit).toBeNull();
    expect(applyField(hole(), "applies_to", "").applies_to).toBeNull();
  });

  it("stores typed numbers as numbers", () => {
    expect(applyField(hole(), "value", "[24.85, 25.15]").value).toEqual([24.85, 25.15]);
    expect(applyField(hole(), "confidence", "0.75").confidence).toBe(0.75);
    expect(applyField(hole(), "page", "2").page).toBe(2);
  });

  it("edits one limit and keeps the other", () => {
    expect(applyField(hole(), "limits.upper", "25.2").limits).toEqual({
      lower: 24.85,
      upper: 25.2,
    });
  });

  it("drops the limits when both are cleared, and starts them from one typed number", () => {
    const cleared = applyField(applyField(hole(), "limits.lower", ""), "limits.upper", "");
    expect(cleared.limits).toBeNull();
    expect(applyField(cleared, "limits.upper", "0.1").limits).toEqual({ lower: "", upper: 0.1 });
  });

  it("keeps the kind when the new callout allows it and resets it when not", () => {
    const frame = applyField(hole(), "callout", "feature_control_frame");
    expect(frame.kind).toBe("straightness");
    expect(
      applyField(applyField(frame, "kind", "position"), "callout", "feature_control_frame").kind,
    ).toBe("position");
  });
});

describe("addDatum", () => {
  it("adds a trimmed datum reference once and ignores blanks", () => {
    expect(addDatum(["A"], " B(M) ")).toEqual(["A", "B(M)"]);
    expect(addDatum(["A"], "A")).toEqual(["A"]);
    expect(addDatum(["A"], "  ")).toEqual(["A"]);
  });

  it("adds each datum of a comma list", () => {
    expect(addDatum(["A"], "B, C,, A")).toEqual(["A", "B", "C"]);
  });
});
