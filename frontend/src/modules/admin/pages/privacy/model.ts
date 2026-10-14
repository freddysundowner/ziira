/** Pure helpers for the privacy screens: what a request has found, which records a step covers, dates and wording. */
import type { BadgeTone, Schemas } from "@/sdk";

export type PrivacyRequest = Schemas["ziira__kernel__api__privacy_routes__RequestOut"];
export type Found = Schemas["FoundOut"];
export type RequestType = "access" | "correction" | "erasure";

export const REQUEST_TYPES: RequestType[] = ["access", "correction", "erasure"];
export const REQUEST_STATUSES = ["open", "in_progress", "completed", "refused"] as const;
export const STATUS_TONE: Record<string, BadgeTone> = { open: "info", in_progress: "warn", completed: "ok", refused: "neutral" };

export const isFinished = (r: Pick<PrivacyRequest, "status">): boolean => r.status === "completed" || r.status === "refused";

/** The search has run once the request left "open" (a search, an export or an erasure all move it on). */
export const hasSearched = (r: Pick<PrivacyRequest, "status" | "found">): boolean => r.status !== "open" || r.found.length > 0;

export interface SourceGroup {
  source: string;
  records: Found[];
  exact: number;
  possible: number;
}

/** Found records grouped by the unit that holds them, units in alphabetical order, exact matches before possible ones. */
export function groupBySource(found: readonly Found[]): SourceGroup[] {
  const groups = new Map<string, Found[]>();
  for (const f of found) groups.set(f.source, [...(groups.get(f.source) ?? []), f]);
  return [...groups.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([source, records]) => ({
      source,
      records: [...records].sort((a, b) => Number(a.match === "possible") - Number(b.match === "possible") || a.label.localeCompare(b.label)),
      exact: records.filter((r) => r.match === "exact").length,
      possible: records.filter((r) => r.match === "possible").length,
    }));
}

/** The records an export or erasure covers: every exact match plus the possible matches a person confirmed. */
export function selectedRecords(found: readonly Found[], confirmedPossible: ReadonlySet<string>): Found[] {
  return found.filter((f) => f.match === "exact" || confirmedPossible.has(f.record_id));
}

/** Record ids to send; undefined when nothing is selected (the API then falls back to exact matches and says so). */
export function recordIdsFor(found: readonly Found[], confirmedPossible: ReadonlySet<string>): string[] | undefined {
  const ids = selectedRecords(found, confirmedPossible).map((f) => f.record_id);
  return ids.length ? ids : undefined;
}

/** Counts of the selected records per unit, for "this will change 3 records in CRM". */
export function countBySource(records: readonly Found[]): { source: string; count: number }[] {
  const counts = new Map<string, number>();
  for (const r of records) counts.set(r.source, (counts.get(r.source) ?? 0) + 1);
  return [...counts.entries()].map(([source, count]) => ({ source, count })).sort((a, b) => a.source.localeCompare(b.source));
}

/** The same comparison the server makes: spaces collapsed, upper and lower case ignored. */
const squash = (text: string): string => text.split(/\s+/).filter(Boolean).join(" ").toLowerCase();
export const subjectMatches = (typed: string, subject: string): boolean => typed.trim() !== "" && squash(typed) === squash(subject);

export const reasonIsEnough = (reason: string): boolean => reason.trim().length >= 5;

export type Due = "done" | "overdue" | "soon" | "later";

/** Whole days from `today` to `dueDate` (both YYYY-MM-DD); negative when past. */
export function daysUntil(dueDate: string, today: string): number {
  return Math.round((Date.parse(`${dueDate}T00:00:00Z`) - Date.parse(`${today}T00:00:00Z`)) / 86_400_000);
}

/** How urgent a request is: the server says `overdue`; "soon" is the last week. */
export function dueState(r: Pick<PrivacyRequest, "status" | "overdue" | "due_date">, today: string): Due {
  if (isFinished(r)) return "done";
  if (r.overdue || daysUntil(r.due_date, today) < 0) return "overdue";
  return daysUntil(r.due_date, today) <= 7 ? "soon" : "later";
}

export const exportFileName = (number: string): string => `${number.replace(/[^\w.-]+/g, "_")}-export.json`;

export interface ExportEntry { at: string; by: string | null; records: number }

export function exportsOf(outcome: PrivacyRequest["outcome"]): ExportEntry[] {
  const list = outcome?.exports;
  if (!Array.isArray(list)) return [];
  return list.map((e: Record<string, unknown>) => ({ at: String(e.at ?? ""), by: e.by ? String(e.by) : null, records: Number(e.records ?? 0) }));
}

export interface Kept { what: string; why: string }
export interface ErasureResult { source: string; kind: string; status: string; changed: string[]; kept: Kept[]; message: string }
export interface ErasureOutcome { at: string; reason: string; approvedBy: string | null; requestedBy: string | null; results: ErasureResult[] }

/** What an erasure did, read defensively from the request's outcome (a JSON bag): nothing if no erasure has run. */
export function erasureOf(outcome: PrivacyRequest["outcome"]): ErasureOutcome | null {
  const e = outcome?.erasure as Record<string, unknown> | undefined;
  if (!e || !Array.isArray(e.results)) return null;
  return {
    at: String(e.at ?? ""), reason: String(e.reason ?? ""), approvedBy: e.approved_by ? String(e.approved_by) : null,
    requestedBy: e.requested_by ? String(e.requested_by) : null,
    results: (e.results as Record<string, unknown>[]).map((r) => ({
      source: String(r.source ?? ""), kind: String(r.kind ?? ""), status: String(r.status ?? ""),
      changed: Array.isArray(r.changed) ? r.changed.map(String) : [], message: String(r.message ?? ""),
      kept: Array.isArray(r.kept) ? (r.kept as Record<string, unknown>[]).map((k) => ({ what: String(k.what ?? ""), why: String(k.why ?? "") })) : [],
    })),
  };
}

export const closingNoteOf = (outcome: PrivacyRequest["outcome"]): string | null =>
  typeof outcome?.closing_note === "string" ? outcome.closing_note : null;

export interface RetentionRule { unit: string; code: string; what: string; basis: string; setting: string | null; period: string; at_end: string; eligible: number }
export interface RetentionView {
  company_id: string;
  settings: Record<string, number>;
  rules: RetentionRule[];
  never_deleted: string[];
}

/** The retention view comes back untyped; accept it only if it has the shape the screen needs. */
export function asRetention(data: unknown): RetentionView {
  const d = data as Partial<RetentionView> | null;
  return {
    company_id: String(d?.company_id ?? ""), settings: d?.settings ?? {}, rules: Array.isArray(d?.rules) ? d.rules : [],
    never_deleted: Array.isArray(d?.never_deleted) ? d.never_deleted : [],
  };
}

/** The retention rules of the units a set of records sits in. */
export const rulesForSources = (rules: readonly RetentionRule[], sources: readonly string[]): RetentionRule[] =>
  rules.filter((r) => sources.includes(r.unit));
