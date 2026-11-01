// Maps what the person types in the record form to document fields and back.
import { type Callout, KINDS_BY_CALLOUT } from "./schema";
import type { Typed, Value } from "./types";

const NUMBER = /^[-+]?(\d+\.?\d*|\.\d+)$/;

/** A number, "[lower, upper]" (brackets optional), or blank for none. */
export function parseValue(text: string): Value["value"] {
  const trimmed = text.trim();
  if (trimmed === "") return null;
  const parts = trimmed.replace(/^\[(.*)\]$/, "$1").split(",");
  if (parts.length === 1) return parseNumber(trimmed);
  const [lower, upper] = parts.map(parseNumber);
  if (parts.length === 2 && typeof lower === "number" && typeof upper === "number") {
    return [lower, upper];
  }
  return text;
}

export function parseNumber(text: string): Typed<number> {
  const trimmed = text.trim();
  return NUMBER.test(trimmed) ? Number(trimmed) : text;
}

export function formatValue(value: Value["value"]): string {
  if (value === null) return "";
  if (Array.isArray(value)) return `[${value[0]}, ${value[1]}]`;
  return String(value);
}

/** The record fields a form control edits as text; datums and bbox have their own editors. */
export type FormField =
  | "id"
  | "raw"
  | "callout"
  | "kind"
  | "tolerance_style"
  | "value"
  | "unit"
  | "feature_id"
  | "applies_to"
  | "limits.lower"
  | "limits.upper"
  | "meaning"
  | "page"
  | "confidence"
  | "status";

const OPTIONAL = new Set<FormField>(["unit", "feature_id", "applies_to"]);

export function applyField(value: Value, field: FormField, text: string): Value {
  if (OPTIONAL.has(field)) return { ...value, [field]: text === "" ? null : text };
  if (field === "value") return { ...value, value: parseValue(text) };
  if (field === "confidence") return { ...value, confidence: parseNumber(text) };
  if (field === "limits.lower" || field === "limits.upper") {
    const limits = { lower: "", upper: "", ...value.limits, [field.slice(7)]: parseNumber(text) };
    return { ...value, limits: isBlank(limits.lower) && isBlank(limits.upper) ? null : limits };
  }
  if (field === "callout") {
    const kinds = KINDS_BY_CALLOUT[text as Callout] ?? [];
    const kind = kinds.includes(value.kind) ? value.kind : (kinds[0] ?? value.kind);
    return { ...value, callout: text as Callout, kind };
  }
  // The page is picked from a list of the drawing's pages, so it always parses.
  if (field === "page") return { ...value, page: Number(text) };
  return { ...value, [field]: text };
}

function isBlank(input: Typed<number>): boolean {
  return typeof input === "string" && input.trim() === "";
}

/** Adds each datum of `text`, which may be a comma list, once; blanks are ignored. */
export function addDatum(datums: string[], text: string): string[] {
  return text
    .split(",")
    .map((part) => part.trim())
    .reduce(
      (list, datum) => (datum === "" || list.includes(datum) ? list : [...list, datum]),
      datums,
    );
}
