// Whole-document edits: adding and removing records while keeping ids and references sound.
import type { Bbox } from "./bbox";
import type { Feature, GoldDocument, Value } from "./types";

export function addValue(
  document: GoldDocument,
  page: number,
  bbox: Bbox,
): { document: GoldDocument; index: number } {
  const value: Value = {
    id: nextValueId(document),
    raw: "",
    callout: "dimension",
    kind: "linear",
    tolerance_style: "none",
    value: null,
    unit: document.title_block.units ?? null,
    feature_id: null,
    applies_to: null,
    datums: [],
    limits: null,
    meaning: "",
    page,
    bbox,
    confidence: 1,
    status: "draft",
  };
  return {
    document: { ...document, values: [...document.values, value] },
    index: document.values.length,
  };
}

export function addFeature(
  document: GoldDocument,
  page: number,
): { document: GoldDocument; index: number } {
  const ids = new Set(document.features.map((feature) => feature.id));
  let n = 1;
  while (ids.has(`feature_${n}`)) n += 1;
  const feature: Feature = { id: `feature_${n}`, type: "other", label: "", description: "", page };
  return {
    document: { ...document, features: [...document.features, feature] },
    index: document.features.length,
  };
}

/** Edits a feature's fields other than its id; renameFeature changes the id. */
export function updateFeature(
  document: GoldDocument,
  index: number,
  patch: Partial<Omit<Feature, "id">>,
): GoldDocument {
  return {
    ...document,
    features: document.features.map((item, i) => (i === index ? { ...item, ...patch } : item)),
  };
}

/**
 * Renames a feature and carries the new id to the values that point at it. A rename onto
 * another feature's id is refused: the values of both would then point at one id for good.
 */
export function renameFeature(
  document: GoldDocument,
  index: number,
  id: string,
): { document: GoldDocument } | { taken: string } {
  const old = document.features[index]!.id;
  if (id === old) return { document };
  if (document.features.some((feature, i) => i !== index && feature.id === id))
    return { taken: id };
  return {
    document: {
      ...document,
      features: document.features.map((item, i) => (i === index ? { ...item, id } : item)),
      values: document.values.map((value) =>
        value.feature_id === old ? { ...value, feature_id: id } : value,
      ),
    },
  };
}

/** Value ids are "<drawing short>-<nn>", such as ctc01-07; see drawing_short in models.py. */
function nextValueId(document: GoldDocument): string {
  const match = /^nist_([a-z]+)_(\d+)_/.exec(document.drawing);
  const prefix = match ? `${match[1]}${match[2]}` : (document.values[0]?.id.split("-")[0] ?? "v");
  const numbers = document.values.map((value) => Number(value.id.split("-")[1]) || 0);
  return `${prefix}-${String(Math.max(0, ...numbers) + 1).padStart(2, "0")}`;
}

export function deleteValue(document: GoldDocument, index: number): GoldDocument {
  return { ...document, values: document.values.filter((_, i) => i !== index) };
}

/** Deletes a feature unless a value still points at it; then names those values. */
export function deleteFeature(
  document: GoldDocument,
  index: number,
): { document: GoldDocument } | { usedBy: string[] } {
  const id = document.features[index]!.id;
  const usedBy = document.values
    .filter((value) => value.feature_id === id)
    .map((value) => value.id);
  if (usedBy.length > 0) return { usedBy };
  return { document: { ...document, features: document.features.filter((_, i) => i !== index) } };
}

/** A gold file as stored: the API returns it as is, so fields with schema defaults may be absent. */
export type StoredDocument = Pick<GoldDocument, "drawing" | "page_count"> &
  Partial<Omit<GoldDocument, "values">> & { values?: Partial<Value>[] };

/** Fills the defaults models.py gives (title_block, features, values, datums, applies_to, status). */
export function withDefaults(stored: StoredDocument): GoldDocument {
  return {
    ...stored,
    title_block: stored.title_block ?? {},
    features: stored.features ?? [],
    values: (stored.values ?? []).map(
      (value) =>
        ({
          ...value,
          applies_to: value.applies_to ?? null,
          datums: value.datums ?? [],
          status: value.status ?? "draft",
        }) as Value,
    ),
  };
}
