// The gold document as the API sends and accepts it; see src/resourcly/models.py.
import type { Bbox } from "./bbox";
import type { Callout, FeatureType, Status, ToleranceStyle, Unit } from "./schema";

/**
 * A number field the person typed that does not parse holds that text, so the API
 * rejects it and names the field instead of the screen dropping the edit.
 */
export type Typed<T> = T | string;

export interface TitleBlock {
  title?: string | null;
  revision?: string | null;
  units?: "mm" | "in" | null;
  units_source?: "stated" | "inferred" | null;
  drawing_number?: string | null;
  sheet_note?: string | null;
  standard?: string | null;
}

export interface Feature {
  id: string;
  type: FeatureType;
  label: string;
  description: string;
  page: number;
}

export interface Limits {
  lower: Typed<number>;
  upper: Typed<number>;
}

export interface Value {
  id: string;
  raw: string;
  callout: Callout;
  kind: string;
  tolerance_style: ToleranceStyle;
  value: Typed<number | [number, number] | null>;
  unit: Unit | null;
  feature_id: string | null;
  applies_to: string | null;
  datums: string[];
  limits: Limits | null;
  meaning: string;
  page: number;
  bbox: Bbox;
  confidence: Typed<number>;
  status: Status;
}

export interface GoldDocument {
  drawing: string;
  page_count: number;
  /** The pages labelled in full; absent means every page. */
  page_coverage?: number[];
  title_block: TitleBlock;
  features: Feature[];
  values: Value[];
}

export interface Issue {
  loc: (string | number)[];
  message: string;
}

export interface DrawingSummary {
  drawing: string;
  page_count: number;
  has_gold: boolean;
  source: "drawings" | "partial" | null;
  values: number;
  approved: number;
  issues: number;
}
