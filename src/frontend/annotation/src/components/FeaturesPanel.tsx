import { useId, useState } from "react";
import { deleteFeature, renameFeature, updateFeature } from "../document";
import { messagesByField } from "../issues";
import { FEATURE_TYPES } from "../schema";
import { Select } from "./RecordForm";
import type { Feature, GoldDocument, Issue } from "../types";

interface Props {
  document: GoldDocument;
  issues: Issue[];
  readOnly: boolean;
  onChange: (document: GoldDocument) => void;
}

/** The drawing's features as an inline-editable list, with how many values point at each. */
export function FeaturesPanel({ document, issues, readOnly, onChange }: Props) {
  const [blocked, setBlocked] = useState<string | null>(null);
  const pages = Array.from({ length: document.page_count }, (_, i) => i + 1);

  if (document.features.length === 0) {
    return <p className="empty">No features yet.{readOnly ? "" : " Add one with Add feature."}</p>;
  }

  return (
    <div className="features">
      {blocked && (
        <p className="record-issue" role="alert">
          {blocked}
        </p>
      )}
      {document.features.map((feature, index) => {
        const users = document.values.filter((value) => value.feature_id === feature.id).length;
        const byField = messagesByField(issues, "features", index);
        const edit = (patch: Partial<Omit<Feature, "id">>) =>
          onChange(updateFeature(document, index, patch));
        if (readOnly) {
          return (
            <article key={index} className="feature">
              <header>
                <strong>{feature.label}</strong>
                <span className="chip">{feature.type}</span>
              </header>
              <p>{feature.description}</p>
              <footer>
                {feature.id} · page {feature.page} · {users} {users === 1 ? "value" : "values"}
              </footer>
            </article>
          );
        }
        return (
          <article
            key={index}
            className="feature"
            data-invalid={Object.keys(byField).length > 0 || undefined}
          >
            <div className="feature-row">
              <input
                aria-label={`Feature ${index + 1} label`}
                name={`features.${index}.label`}
                className="feature-label"
                value={feature.label}
                placeholder="Label"
                onChange={(e) => edit({ label: e.target.value })}
              />
              <Select
                aria-label={`Feature ${index + 1} type`}
                name={`features.${index}.type`}
                value={feature.type}
                options={FEATURE_TYPES}
                onChange={(type) => edit({ type: type as Feature["type"] })}
              />
              <button
                type="button"
                className="icon danger"
                aria-label={`Delete feature ${feature.id}`}
                title="Delete feature"
                onClick={() => {
                  const result = deleteFeature(document, index);
                  if ("usedBy" in result) {
                    setBlocked(`${feature.id} is still used by ${result.usedBy.join(", ")}.`);
                  } else {
                    setBlocked(null);
                    onChange(result.document);
                  }
                }}
              >
                ×
              </button>
            </div>
            <textarea
              aria-label={`Feature ${index + 1} description`}
              name={`features.${index}.description`}
              rows={2}
              value={feature.description}
              placeholder="Description"
              onChange={(e) => edit({ description: e.target.value })}
            />
            <div className="feature-row small">
              <FeatureIdInput
                key={feature.id}
                label={`Feature ${index + 1} id`}
                name={`features.${index}.id`}
                id={feature.id}
                onRename={(id) => {
                  const result = renameFeature(document, index, id);
                  if ("taken" in result) return `${result.taken} is already a feature id`;
                  onChange(result.document);
                  return null;
                }}
              />
              <select
                aria-label={`Feature ${index + 1} page`}
                name={`features.${index}.page`}
                value={feature.page}
                onChange={(e) => edit({ page: Number(e.target.value) })}
              >
                {pages.map((page) => (
                  <option key={page} value={page}>
                    page {page}
                  </option>
                ))}
              </select>
              <span className="muted">
                {users} {users === 1 ? "value" : "values"}
              </span>
            </div>
            {Object.entries(byField).map(([field, messages]) => (
              <p key={field} className="field-issue">
                {field && `${field}: `}
                {messages.join("; ")}
              </p>
            ))}
          </article>
        );
      })}
    </div>
  );
}

interface FeatureIdInputProps {
  label: string;
  name: string;
  id: string;
  /** Applies the new id, or returns why it was refused. */
  onRename: (id: string) => string | null;
}

/**
 * A feature id renames on Enter or on leaving the field, not on every key, so typing through
 * another feature's id on the way to a new one never moves values; Escape puts the id back.
 */
function FeatureIdInput({ label, name, id, onRename }: FeatureIdInputProps) {
  const [text, setText] = useState(id);
  const [refused, setRefused] = useState<string | null>(null);
  const describedBy = useId();
  const commit = () => setRefused(text === id ? null : onRename(text));
  return (
    <span className="feature-id">
      <input
        aria-label={label}
        name={name}
        className="mono"
        value={text}
        aria-invalid={refused ? true : undefined}
        aria-describedby={refused ? describedBy : undefined}
        onChange={(e) => setText(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") commit();
          if (e.key === "Escape") {
            setText(id);
            setRefused(null);
          }
        }}
      />
      {refused && (
        <span id={describedBy} className="field-issue" role="alert">
          {refused}
        </span>
      )}
    </span>
  );
}
