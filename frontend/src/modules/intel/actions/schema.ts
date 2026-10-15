/** Pure rules for the forms the server describes with a small JSON-schema-like vocabulary (a suggestion's parameters, an automatic rule's conditions). */
import { humanise } from "@/sdk";

export type FieldType = "string" | "integer" | "number" | "boolean" | "uuid" | "date";

export interface FieldDef {
  name: string;
  type: FieldType;
  title: string;
  description?: string;
  options?: string[];
  minimum?: number;
  maximum?: number;
  maxLength?: number;
  editable: boolean;
  required: boolean;
}

const TYPES: readonly string[] = ["string", "integer", "number", "boolean", "uuid", "date"];

/** The fields a schema describes, in the order the server lists them. */
export function fieldsOf(schema: Record<string, unknown> | null | undefined): FieldDef[] {
  const props = (schema?.properties ?? {}) as Record<string, Record<string, unknown>>;
  const required = Array.isArray(schema?.required) ? (schema.required as string[]) : [];
  return Object.entries(props).map(([name, p]) => ({
    name,
    type: (TYPES.includes(String(p.type)) ? p.type : "string") as FieldType,
    title: typeof p.title === "string" ? p.title : humanise(name),
    description: typeof p.description === "string" ? p.description : undefined,
    options: Array.isArray(p.enum) ? p.enum.map(String) : undefined,
    minimum: typeof p.minimum === "number" ? p.minimum : undefined,
    maximum: typeof p.maximum === "number" ? p.maximum : undefined,
    maxLength: typeof p.max_length === "number" ? p.max_length : undefined,
    editable: p.editable !== false,
    required: required.includes(name),
  }));
}

export type Draft = Record<string, string>;

/** Saved values as the text the inputs hold. */
export function toDraft(fields: readonly FieldDef[], values: Record<string, unknown>): Draft {
  return Object.fromEntries(fields.map((f) => [f.name, values[f.name] === null || values[f.name] === undefined ? "" : String(values[f.name])]));
}

/** The fields a person can change in the form: ids are never typed, and the server marks some parameters fixed. */
export const editableFields = (fields: readonly FieldDef[], keepBranch = false): FieldDef[] =>
  fields.filter((f) => f.editable && (f.type !== "uuid" || (keepBranch && f.name === "branch_id")));

export interface FieldProblem {
  code: "required" | "whole" | "number" | "date" | "min" | "max" | "option" | "length";
  limit?: string;
}

const DECIMAL = /^-?\d+(\.\d+)?$/;
const WHOLE = /^-?\d+$/;
const DAY = /^\d{4}-\d{2}-\d{2}$/;

/** What is wrong with each field (mirrors the server's checks; the server's own message wins when it differs). */
export function validate(fields: readonly FieldDef[], draft: Draft): Record<string, FieldProblem> {
  const out: Record<string, FieldProblem> = {};
  for (const f of fields) {
    const text = (draft[f.name] ?? "").trim();
    if (text === "") {
      if (f.required && f.type !== "boolean") out[f.name] = { code: "required" };
      continue;
    }
    const problem = check(f, text);
    if (problem) out[f.name] = problem;
  }
  return out;
}

function check(f: FieldDef, text: string): FieldProblem | null {
  if (f.options && !f.options.includes(text)) return { code: "option" };
  if (f.type === "integer" && !WHOLE.test(text)) return { code: "whole" };
  if (f.type === "number" && !DECIMAL.test(text)) return { code: "number" };
  if (f.type === "date" && !DAY.test(text)) return { code: "date" };
  if (f.type === "integer" || f.type === "number") {
    if (f.minimum !== undefined && Number(text) < f.minimum) return { code: "min", limit: String(f.minimum) };
    if (f.maximum !== undefined && Number(text) > f.maximum) return { code: "max", limit: String(f.maximum) };
  }
  if (f.type === "string" && f.maxLength !== undefined && text.length > f.maxLength) return { code: "length", limit: String(f.maxLength) };
  return null;
}

/** The values to send: only the given fields, empty optional ones left out, whole numbers as numbers and decimals as text. */
export function toValues(fields: readonly FieldDef[], draft: Draft): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const f of fields) {
    const text = (draft[f.name] ?? "").trim();
    if (f.type === "boolean") out[f.name] = text === "true";
    else if (text === "") continue;
    else out[f.name] = f.type === "integer" ? Number(text) : text;
  }
  return out;
}

export interface Wording {
  yes: string;
  no: string;
  branchName: (id: string) => string | undefined;
  /** Formats a field the caller knows better (an amount in the company's currency); undefined means "use the plain text". */
  special?: (field: FieldDef, value: unknown) => string | undefined;
}

/** One condition as words: "Largest amount: KES 5,000". */
export function describeValue(field: FieldDef, value: unknown, w: Wording): string {
  const special = w.special?.(field, value);
  if (special !== undefined) return special;
  if (typeof value === "boolean") return value ? w.yes : w.no;
  if (field.type === "uuid") return w.branchName(String(value)) ?? "—";
  if (field.options) return humanise(String(value));
  return String(value);
}

/** The conditions a rule has, one phrase each, in schema order; fields without a value are left out. */
export function describeConditions(fields: readonly FieldDef[], conditions: Record<string, unknown>, w: Wording): string[] {
  return fields
    .filter((f) => conditions[f.name] !== undefined && conditions[f.name] !== null && conditions[f.name] !== "")
    .map((f) => `${f.title}: ${describeValue(f, conditions[f.name], w)}`);
}

/** The server's message for one field, from the keys a 422 uses ("params.quantity", "conditions.max_amount" or just the name). */
export function serverMessage(fields: Record<string, string>, name: string): string | undefined {
  return fields[name] ?? fields[`params.${name}`] ?? fields[`conditions.${name}`];
}
