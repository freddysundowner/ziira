import type { Schemas } from "@/sdk";

export type Batch = Schemas["BatchOut"];
export type Column = Schemas["ColumnOut"];
export type Counts = Schemas["CountsOut"];

/** Where the wizard is, from what the server says about the import: 0 upload, 1 columns, 2 review, 3 import and report. */
export function stepOf(status: Batch["status"] | undefined): 0 | 1 | 2 | 3 {
  if (status === "uploaded") return 1;
  if (status === "validated") return 2;
  if (status === "committing" || status === "done" || status === "reverted") return 3;
  return 0;
}

/** The fields still without a column, and the columns chosen for more than one field. */
export function mappingProblems(columns: readonly Column[], mapping: Record<string, string | null>): { missing: string[]; duplicated: string[] } {
  const missing = columns.filter((c) => c.required && !mapping[c.name]).map((c) => c.name);
  const used = Object.values(mapping).filter((h): h is string => !!h);
  const duplicated = [...new Set(used.filter((h, i) => used.indexOf(h) !== i))];
  return { missing, duplicated };
}

/** How far the background import has got, 0 to 100: rows handled out of rows handled plus rows still waiting. */
export function progressPercent(counts: Counts): number {
  const handled = counts.imported + counts.failed;
  const total = handled + counts.valid;
  return total === 0 ? 100 : Math.floor((handled / total) * 100);
}

/** Rows the user has to fix: rejected by the check, or failed while importing. */
export const problemRows = (counts: Counts): number => counts.invalid + counts.failed;

/** Whether the import can be started: something valid to import, and for a whole-file import no problem with the file as a whole. */
export function canImport(batch: Batch, confirmed: boolean): boolean {
  if (batch.counts.valid === 0) return false;
  if (batch.whole_file && (batch.counts.invalid > 0 || batch.file_check.problems.length > 0)) return false;
  return !batch.file_check.confirm || confirmed;
}

export type RowFilter = "all" | "problems" | "valid" | "skipped" | "imported";

/** The query the rows endpoint needs for a filter. */
export function filterQuery(filter: RowFilter): { only_errors?: boolean; status?: Schemas["RowOut"]["status"] } {
  if (filter === "problems") return { only_errors: true };
  if (filter === "valid" || filter === "skipped" || filter === "imported") return { status: filter };
  return {};
}
