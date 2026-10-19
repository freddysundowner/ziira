import type { Schemas } from "@/sdk";

export type FieldRow = Schemas["CustomFieldOut"];
export type EntityRow = Schemas["CustomFieldEntityOut"];

export const KINDS = ["text", "number", "date", "bool", "choice"] as const;
export type Kind = (typeof KINDS)[number];

/** A field key from a name: lowercase letters, digits and '_', starting with a letter, at most 40 characters ("Hair type" is "hair_type"). */
export function keyFromLabel(label: string): string {
  const base = label.normalize("NFKD").replace(/\p{M}|[^\p{ASCII}]/gu, "").toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
  const key = /^[a-z]/.test(base) ? base : base ? `f_${base}` : "";
  return key.slice(0, 40).replace(/_+$/, "");
}

/** One choice per line, trimmed, without blanks or repeats. */
export function parseChoices(text: string): string[] {
  return [...new Set(text.split("\n").map((c) => c.trim()).filter(Boolean))];
}

/** Fields grouped by record type, each group in the business's order; record types with no fields yet still get a group. */
export function groupByEntity(entities: readonly EntityRow[], fields: readonly FieldRow[]): { entity: EntityRow; fields: FieldRow[] }[] {
  return entities.map((entity) => ({
    entity,
    fields: fields.filter((f) => f.entity_type === entity.entity_type).sort((a, b) => a.sort_order - b.sort_order || a.label.localeCompare(b.label)),
  }));
}

/** The ids of a record type's fields after moving one up or down (the same list when it cannot move). */
export function moved(ids: readonly string[], id: string, by: -1 | 1): string[] {
  const at = ids.indexOf(id);
  const to = at + by;
  if (at < 0 || to < 0 || to >= ids.length) return [...ids];
  const out = [...ids];
  [out[at], out[to]] = [out[to], out[at]];
  return out;
}
