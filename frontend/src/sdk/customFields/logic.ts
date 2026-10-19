/** Custom fields in the browser, as plain functions: which values the form holds, what is wrong with them, what to send. */
import type { Schemas } from "../api";

export type CustomFieldDef = Schemas["CustomFieldOut"];
/** What the form holds for each field key: text for every kind; a yes/no field holds "true", "false" or "". */
export type CustomValues = Record<string, string>;
export type CustomFieldProblem = "required" | "number" | "date";

const NUMBER = /^-?\d+(\.\d+)?$/;
const DATE = /^\d{4}-\d{2}-\d{2}$/;

/** The server's saved values as form text. */
export function toFormValues(fields: readonly CustomFieldDef[], saved: Record<string, unknown>): CustomValues {
  const out: CustomValues = {};
  for (const f of fields) {
    const v = saved[f.key];
    out[f.key] = v === undefined || v === null ? "" : typeof v === "boolean" ? String(v) : String(v);
  }
  return out;
}

/** What is wrong with the form values, by field key (the server checks again; this saves a round trip). */
export function validateCustomValues(fields: readonly CustomFieldDef[], values: CustomValues): Record<string, CustomFieldProblem> {
  const problems: Record<string, CustomFieldProblem> = {};
  for (const f of fields) {
    if (!f.active) continue;
    const v = (values[f.key] ?? "").trim();
    if (v === "") {
      if (f.required) problems[f.key] = "required";
    } else if (f.kind === "number" && !NUMBER.test(v)) {
      problems[f.key] = "number";
    } else if (f.kind === "date" && (!DATE.test(v) || Number.isNaN(Date.parse(v)))) {
      problems[f.key] = "date";
    }
  }
  return problems;
}

/** The request body: only the fields that changed since `saved` (an empty value clears a field). Booleans are sent as booleans. */
export function toPayload(fields: readonly CustomFieldDef[], values: CustomValues, saved: CustomValues): Record<string, string | boolean | null> {
  const out: Record<string, string | boolean | null> = {};
  for (const f of fields) {
    const now = (values[f.key] ?? "").trim();
    if (now === (saved[f.key] ?? "").trim()) continue;
    out[f.key] = now === "" ? null : f.kind === "bool" ? now === "true" : now;
  }
  return out;
}

/** The fields people fill in: active ones, in the business's order. */
export const visibleFields = (fields: readonly CustomFieldDef[]): CustomFieldDef[] =>
  fields.filter((f) => f.active).sort((a, b) => a.sort_order - b.sort_order || a.label.localeCompare(b.label));

/** A saved value as people read it ("Yes", a date as stored, the number as typed). */
export function displayValue(f: CustomFieldDef, raw: string, yes: string, no: string): string {
  if (raw === "") return "";
  return f.kind === "bool" ? (raw === "true" ? yes : no) : raw;
}
