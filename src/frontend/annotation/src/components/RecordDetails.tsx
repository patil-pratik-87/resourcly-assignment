import { formatValue } from "../form";
import type { GoldDocument, Value } from "../types";

const words = (text: string) => text.replaceAll("_", " ");

/** The read-only view of a value for demos: what was read and what it means. */
export function RecordDetails({ document, value }: { document: GoldDocument; value: Value }) {
  const feature = document.features.find((item) => item.id === value.feature_id);
  const limits = value.limits ? `${value.limits.lower} to ${value.limits.upper}` : "none";
  const rows: [string, string][] = [
    ["Callout", words(value.callout)],
    ["Kind", words(value.kind ?? "none")],
    ["Tolerance", words(value.tolerance_style)],
    ["Value", [formatValue(value.value) || "none", value.unit ?? ""].join(" ").trim()],
    ["Limits", value.limits ? `${limits} ${value.unit ?? ""}`.trim() : limits],
    ["Datums", value.datums.join(", ") || "none"],
    ["Feature", feature ? feature.label : (value.feature_id ?? "none")],
    ["Applies to", value.applies_to ?? "none"],
    ["Confidence", String(value.confidence)],
    ["Id", value.id],
  ];
  return (
    <div className="details">
      <p className="details-raw">{value.raw}</p>
      <p className="details-meaning">{value.meaning}</p>
      <dl>
        {rows.map(([label, text]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{text}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
