import { type ReactNode, useId, useState } from "react";

export interface ControlProps {
  id: string;
  "aria-describedby"?: string;
  "aria-invalid"?: true;
}

interface FieldProps {
  label: string;
  issues?: string[];
  hint?: string;
  className?: string;
  children: (control: ControlProps) => ReactNode;
}

/** A labelled control with the validation issues the API reported for it underneath. */
export function Field({ label, issues = [], hint, className, children }: FieldProps) {
  const id = useId();
  const described = issues.length > 0 ? `${id}-issues` : hint ? `${id}-hint` : undefined;
  return (
    <div className={`field ${className ?? ""}`} data-invalid={issues.length > 0 || undefined}>
      <label htmlFor={id}>{label}</label>
      {children({
        id,
        "aria-describedby": described,
        "aria-invalid": issues.length > 0 ? true : undefined,
      })}
      {issues.length > 0 ? (
        <p id={`${id}-issues`} className="field-issue">
          {issues.join("; ")}
        </p>
      ) : (
        hint && (
          <p id={`${id}-hint`} className="field-hint">
            {hint}
          </p>
        )
      )}
    </div>
  );
}

interface TypedInputProps<T> extends ControlProps {
  value: T;
  format: (value: T) => string;
  parse: (text: string) => T;
  onText: (text: string) => void;
  placeholder?: string;
  inputMode?: "decimal" | "text";
}

/**
 * A text box for a parsed field. It keeps what the person typed ("0." or "[1,") while
 * that still means the stored value, and shows the stored value when it changes elsewhere.
 */
export function TypedInput<T>({ value, format, parse, onText, ...props }: TypedInputProps<T>) {
  const [text, setText] = useState(() => format(value));
  // When the stored value changes elsewhere, show it, unless the text already means it.
  const shown = format(value);
  const [synced, setSynced] = useState(shown);
  if (synced !== shown) {
    setSynced(shown);
    if (format(parse(text)) !== shown) setText(shown);
  }
  return (
    <input
      {...props}
      value={text}
      onChange={(event) => {
        setText(event.target.value);
        onText(event.target.value);
      }}
    />
  );
}
