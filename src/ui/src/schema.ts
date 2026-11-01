// The enums of the gold schema. Keep in step with the Literal types in src/resourcly/models.py;
// the API rejects any value outside them, so a drift shows up as a validation issue.

export const FEATURE_TYPES = [
  "hole",
  "cylinder",
  "plane",
  "slot",
  "boss",
  "thread",
  "chamfer",
  "fillet",
  "edge",
  "pattern",
  "other",
] as const;

export const CALLOUTS = [
  "dimension",
  "feature_control_frame",
  "datum_feature_symbol",
  "datum_target",
  "note",
  "title_block",
  "surface_texture",
  "thread",
] as const;

export const CHARACTERISTICS = [
  "straightness",
  "flatness",
  "circularity",
  "cylindricity",
  "profile_of_a_line",
  "profile_of_a_surface",
  "angularity",
  "perpendicularity",
  "parallelism",
  "position",
  "concentricity",
  "symmetry",
  "circular_runout",
  "total_runout",
] as const;

export const TOLERANCE_STYLES = [
  "limits",
  "plus_minus",
  "unilateral",
  "bilateral_unequal",
  "basic",
  "reference",
  "geometric_zone",
  "none",
] as const;

export const UNITS = ["mm", "in", "deg"] as const;
export const STATUSES = ["draft", "approved"] as const;

export type FeatureType = (typeof FEATURE_TYPES)[number];
export type Callout = (typeof CALLOUTS)[number];
export type ToleranceStyle = (typeof TOLERANCE_STYLES)[number];
export type Unit = (typeof UNITS)[number];
export type Status = (typeof STATUSES)[number];

export const KINDS_BY_CALLOUT: Record<Callout, readonly string[]> = {
  feature_control_frame: CHARACTERISTICS,
  dimension: ["diameter", "radius", "linear", "angular"],
  datum_feature_symbol: ["datum_feature"],
  datum_target: ["datum_target"],
  note: ["note"],
  title_block: ["title_block"],
  surface_texture: ["surface_texture"],
  thread: ["thread"],
};

// The fields of each record in models.py; a stored key outside these is one the API rejects.
export const DOCUMENT_FIELDS = [
  "drawing",
  "page_count",
  "page_coverage",
  "title_block",
  "features",
  "values",
];
export const TITLE_BLOCK_FIELDS = [
  "title",
  "revision",
  "units",
  "units_source",
  "drawing_number",
  "sheet_note",
  "standard",
];
export const FEATURE_FIELDS = ["id", "type", "label", "description", "page"];
export const VALUE_FIELDS = [
  "id",
  "raw",
  "callout",
  "kind",
  "tolerance_style",
  "value",
  "unit",
  "feature_id",
  "applies_to",
  "datums",
  "limits",
  "meaning",
  "page",
  "bbox",
  "confidence",
  "status",
];
