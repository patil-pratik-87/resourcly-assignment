import type { Issue } from "./types";

/** The issues whose field path starts with `prefix`, such as ["values", 3]. */
export function issuesUnder(issues: Issue[], ...prefix: (string | number)[]): Issue[] {
  return issues.filter((issue) => prefix.every((part, i) => issue.loc[i] === part));
}

/** Messages of one record's issues by field name; "" holds those that name no field. */
export function messagesByField(
  issues: Issue[],
  section: "values" | "features",
  index: number,
): Record<string, string[]> {
  const byField: Record<string, string[]> = {};
  for (const issue of issuesUnder(issues, section, index)) {
    const field = String(issue.loc[2] ?? "");
    (byField[field] ??= []).push(issue.message);
  }
  return byField;
}

/** The value indexes that have at least one issue. */
export function valuesWithIssues(issues: Issue[]): Set<number> {
  return new Set(
    issues
      .filter((issue) => issue.loc[0] === "values" && typeof issue.loc[1] === "number")
      .map((issue) => issue.loc[1] as number),
  );
}
