import { useState } from "react";
import { isBbox } from "../bbox";
import {
  addDatum,
  applyField,
  type FormField,
  formatValue,
  parseNumber,
  parseValue,
} from "../form";
import { CALLOUTS, KINDS_BY_CALLOUT, TOLERANCE_STYLES, UNITS, VALUE_FIELDS } from "../schema";
import type { GoldDocument, Typed, Value } from "../types";
import { type ControlProps, Field, TypedInput } from "./Field";

interface Props {
  document: GoldDocument;
  value: Value;
  /** Issue messages by field name; "" holds those that name no field. */
  issues: Record<string, string[]>;
  onChange: (value: Value) => void;
}

const formatNumber = (input: Typed<number>) => String(input);

/**
 * The fields this form has a control for. Issues on any other (status, which Approve sets, or a
 * key the schema does not have) are listed at the top so they can be seen and fixed.
 */
const FIELDS_WITH_A_CONTROL = new Set(VALUE_FIELDS.filter((field) => field !== "status"));

/** Every field of one value record, each with the issues the API reported for it. */
export function RecordForm({ document, value, issues, onChange }: Props) {
  const set = (field: FormField) => (text: string) => onChange(applyField(value, field, text));
  // A stored callout outside the schema has no kinds; the Select still shows what is stored.
  const kinds = KINDS_BY_CALLOUT[value.callout] ?? [];
  const pages = Array.from({ length: document.page_count }, (_, i) => i + 1);

  return (
    <form className="record" onSubmit={(event) => event.preventDefault()}>
      {Object.entries(issues)
        .filter(([field]) => !FIELDS_WITH_A_CONTROL.has(field))
        .map(([field, messages]) => (
          <p key={field} className="record-issue">
            {field ? `${field}: ` : ""}
            {messages.join("; ")}
            {field && !VALUE_FIELDS.includes(field) && field in value && (
              <button
                type="button"
                className="link"
                onClick={() => {
                  const rest = { ...(value as unknown as Record<string, unknown>) };
                  delete rest[field];
                  onChange(rest as unknown as Value);
                }}
              >
                Remove {field}
              </button>
            )}
          </p>
        ))}

      <Field label="Raw text" issues={issues.raw} className="wide">
        {(control) => (
          <input
            {...control}
            className="raw"
            value={value.raw}
            onChange={(e) => set("raw")(e.target.value)}
          />
        )}
      </Field>

      <Field label="Callout" issues={issues.callout}>
        {(control) => (
          <Select {...control} value={value.callout} options={CALLOUTS} onChange={set("callout")} />
        )}
      </Field>
      <Field label="Kind" issues={issues.kind}>
        {(control) => (
          <Select {...control} value={value.kind ?? ""} options={kinds} onChange={set("kind")} />
        )}
      </Field>

      <Field label="Tolerance style" issues={issues.tolerance_style}>
        {(control) => (
          <Select
            {...control}
            value={value.tolerance_style}
            options={TOLERANCE_STYLES}
            onChange={set("tolerance_style")}
          />
        )}
      </Field>
      <Field label="Unit" issues={issues.unit}>
        {(control) => (
          <Select
            {...control}
            value={value.unit ?? ""}
            options={UNITS}
            blank="None"
            onChange={set("unit")}
          />
        )}
      </Field>

      <Field label="Value" issues={issues.value} className="third">
        {(control) => (
          <TypedInput
            {...control}
            value={value.value}
            format={formatValue}
            parse={parseValue}
            onText={set("value")}
            placeholder="n or [lo, hi]"
          />
        )}
      </Field>
      <Field label="Lower limit" issues={issues.limits} className="third">
        {(control) => (
          <TypedInput
            {...control}
            value={value.limits?.lower ?? ""}
            format={formatNumber}
            parse={parseNumber}
            onText={set("limits.lower")}
            inputMode="decimal"
            placeholder="none"
          />
        )}
      </Field>
      {/* The API reports both limits as one "limits" field, so each shows its issues. */}
      <Field label="Upper limit" issues={issues.limits} className="third">
        {(control) => (
          <TypedInput
            {...control}
            value={value.limits?.upper ?? ""}
            format={formatNumber}
            parse={parseNumber}
            onText={set("limits.upper")}
            inputMode="decimal"
            placeholder="none"
          />
        )}
      </Field>

      <Field label="Datums" issues={issues.datums} className="wide">
        {(control) => (
          <DatumTags
            {...control}
            datums={value.datums}
            onChange={(datums) => onChange({ ...value, datums })}
          />
        )}
      </Field>

      <Field label="Feature" issues={issues.feature_id}>
        {(control) => (
          <select
            {...control}
            value={value.feature_id ?? ""}
            onChange={(e) => set("feature_id")(e.target.value)}
          >
            <option value="">None</option>
            {value.feature_id !== null &&
              !document.features.some((f) => f.id === value.feature_id) && (
                <option value={value.feature_id}>{value.feature_id} (missing)</option>
              )}
            {document.features.map((feature) => (
              <option key={feature.id} value={feature.id}>
                {feature.label || feature.id}
              </option>
            ))}
          </select>
        )}
      </Field>
      <Field label="Applies to" issues={issues.applies_to}>
        {(control) => (
          <input
            {...control}
            value={value.applies_to ?? ""}
            placeholder="none"
            onChange={(e) => set("applies_to")(e.target.value)}
          />
        )}
      </Field>

      <Field label="Meaning" issues={issues.meaning} className="wide">
        {(control) => (
          <textarea
            {...control}
            rows={3}
            value={value.meaning}
            onChange={(e) => set("meaning")(e.target.value)}
          />
        )}
      </Field>

      <Field label="Id" issues={issues.id} className="third">
        {(control) => (
          <input {...control} value={value.id} onChange={(e) => set("id")(e.target.value)} />
        )}
      </Field>
      <Field label="Confidence" issues={issues.confidence} className="third">
        {(control) => (
          <TypedInput
            {...control}
            value={value.confidence}
            format={formatNumber}
            parse={parseNumber}
            onText={set("confidence")}
            inputMode="decimal"
          />
        )}
      </Field>
      <Field label="Page" issues={issues.page} className="third">
        {(control) => (
          <select {...control} value={value.page} onChange={(e) => set("page")(e.target.value)}>
            {!pages.includes(value.page) && <option value={value.page}>{value.page}</option>}
            {pages.map((page) => (
              <option key={page} value={page}>
                {page}
              </option>
            ))}
          </select>
        )}
      </Field>
      <Field
        label="Box"
        issues={issues.bbox}
        hint={
          isBbox(value.bbox)
            ? "Drag the box or its corners on the page"
            : "Draw a box on the page to place this value"
        }
        className="wide"
      >
        {(control) => (
          <output {...control} className="bbox">
            {isBbox(value.bbox) ? value.bbox.map((n) => n.toFixed(3)).join("  ") : "none"}
          </output>
        )}
      </Field>
    </form>
  );
}

interface SelectProps extends Partial<ControlProps> {
  "aria-label"?: string;
  name?: string;
  value: string;
  options: readonly string[];
  blank?: string;
  onChange: (value: string) => void;
}

/** A schema enum; a stored value outside it is listed first, so the select shows what is stored. */
export function Select({ value, options, blank, onChange, ...control }: SelectProps) {
  const unknown = !options.includes(value) && !(value === "" && blank !== undefined);
  return (
    <select {...control} value={value} onChange={(event) => onChange(event.target.value)}>
      {unknown && (
        <option value={value}>{value === "" ? "(none)" : `${value} (not in the schema)`}</option>
      )}
      {blank !== undefined && <option value="">{blank}</option>}
      {options.map((option) => (
        <option key={option} value={option}>
          {option.replaceAll("_", " ")}
        </option>
      ))}
    </select>
  );
}

interface DatumTagsProps extends ControlProps {
  datums: string[];
  onChange: (datums: string[]) => void;
}

/** Datum references as removable tags; Enter or a comma adds what was typed. */
function DatumTags({ datums, onChange, ...control }: DatumTagsProps) {
  const [text, setText] = useState("");
  const commit = () => {
    if (text.trim()) onChange(addDatum(datums, text));
    setText("");
  };
  return (
    <div className="tags">
      {/* Keyed and removed by position: a gold file may list the same datum twice. */}
      {datums.map((datum, index) => (
        <span key={index} className="tag">
          {datum}
          <button
            type="button"
            aria-label={`Remove datum ${datum}`}
            onClick={() => onChange(datums.filter((_, i) => i !== index))}
          >
            ×
          </button>
        </span>
      ))}
      <input
        {...control}
        value={text}
        placeholder={datums.length ? "" : "Add a datum, such as A"}
        onChange={(event) => {
          // Typing a comma adds the tag (see onKeyDown); a pasted comma list adds all of it.
          if (event.target.value.includes(",")) {
            onChange(addDatum(datums, event.target.value));
            setText("");
          } else {
            setText(event.target.value);
          }
        }}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === ",") {
            event.preventDefault();
            commit();
          } else if (event.key === "Backspace" && text === "" && datums.length) {
            onChange(datums.slice(0, -1));
          }
        }}
        onBlur={commit}
      />
    </div>
  );
}
