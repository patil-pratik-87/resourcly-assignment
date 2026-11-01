import { issuesUnder } from "../issues";
import type { GoldDocument, Issue, TitleBlock } from "../types";
import { Field } from "./Field";

interface Props {
  document: GoldDocument;
  issues: Issue[];
  readOnly: boolean;
  onChange: (document: GoldDocument) => void;
}

const TEXT_FIELDS: [keyof TitleBlock, string][] = [
  ["title", "Title"],
  ["drawing_number", "Drawing number"],
  ["revision", "Revision"],
  ["standard", "Standard"],
  ["sheet_note", "Sheet note"],
];

export function TitleBlockPanel({ document, issues, readOnly, onChange }: Props) {
  const block = document.title_block;
  const set = (field: keyof TitleBlock, text: string) =>
    onChange({ ...document, title_block: { ...block, [field]: text === "" ? null : text } });
  const messages = (field: string) =>
    issuesUnder(issues, "title_block", field).map((issue) => issue.message);

  return (
    <div className="record">
      {TEXT_FIELDS.map(([field, label]) => (
        <Field key={field} label={label} issues={messages(field)} className="wide">
          {(control) =>
            field === "sheet_note" ? (
              <textarea
                {...control}
                rows={3}
                readOnly={readOnly}
                value={block[field] ?? ""}
                onChange={(e) => set(field, e.target.value)}
              />
            ) : (
              <input
                {...control}
                readOnly={readOnly}
                value={block[field] ?? ""}
                onChange={(e) => set(field, e.target.value)}
              />
            )
          }
        </Field>
      ))}
      <Field label="Units" issues={messages("units")}>
        {(control) => (
          <select
            {...control}
            disabled={readOnly}
            value={block.units ?? ""}
            onChange={(e) => set("units", e.target.value)}
          >
            <option value="">Not given</option>
            <option value="mm">mm</option>
            <option value="in">in</option>
          </select>
        )}
      </Field>
      <Field label="Units source" issues={messages("units_source")}>
        {(control) => (
          <select
            {...control}
            disabled={readOnly}
            value={block.units_source ?? ""}
            onChange={(e) => set("units_source", e.target.value)}
          >
            <option value="">Not given</option>
            <option value="stated">stated</option>
            <option value="inferred">inferred</option>
          </select>
        )}
      </Field>
    </div>
  );
}
