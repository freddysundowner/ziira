/** Pure rules of the Jobs screens: stages, drag and drop, item identifiers. No React, no requests. */
import type { BadgeTone } from "@/sdk";

import type { Estimate, Job, JobSummary, Stage, StageRef } from "./types";

export interface Column {
  stage: StageRef;
  jobs: JobSummary[];
}

/** The board's columns in the order the server sent them, each with its jobs (jobs in a stage that is not a column are left out). */
export function groupByStage(stages: readonly StageRef[], jobs: readonly JobSummary[]): Column[] {
  const columns = stages.map((stage) => ({ stage, jobs: [] as JobSummary[] }));
  const byId = new Map(columns.map((c) => [c.stage.id, c]));
  for (const job of jobs) byId.get(job.status.id)?.jobs.push(job);
  return columns;
}

/** True when the workflow lets a job in `from` go to `to` (a card dropped anywhere else is refused). */
export function canMove(workflow: readonly Stage[], from: string, to: string): boolean {
  if (from === to) return false;
  return workflow.find((s) => s.id === from)?.moves_to.includes(to) ?? false;
}

/** The stages a job can go to next, in workflow order. */
export function nextStages(workflow: readonly Stage[], allowed: readonly string[]): Stage[] {
  const ids = new Set(allowed);
  return workflow.filter((s) => ids.has(s.id));
}

export const isCollect = (stage: Pick<StageRef, "role">): boolean => stage.role === "collected";

export const stageTone = (kind: string): BadgeTone => ({ open: "info", waiting: "warn", done: "ok", closed: "neutral" } as Record<string, BadgeTone>)[kind] ?? "neutral";

/** Work lines still counted (a removed line stays on screen, struck through, but is not part of the job). */
export const liveLines = <T extends { voided: boolean }>(lines: readonly T[]): T[] => lines.filter((l) => !l.voided);

/** The estimate being worked on or last sent: the one with the highest version. */
export function latestEstimate(estimates: readonly Estimate[]): Estimate | undefined {
  return estimates.reduce<Estimate | undefined>((best, e) => (!best || e.version > best.version ? e : best), undefined);
}

/** Costs come only to people who may see them: the server sends null otherwise. */
export const showsCost = (job: Pick<Job, "totals">): boolean => job.totals.cost !== null;

export interface IdentifierRow {
  name: string;
  value: string;
}

/** Name/value rows typed at the counter to the object the API keeps: blanks dropped, spaces trimmed, a repeated name keeps its first value. */
export function cleanIdentifiers(rows: readonly IdentifierRow[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (const row of rows) {
    const name = row.name.trim().slice(0, 40);
    const value = row.value.trim().slice(0, 120);
    if (name && value && !(name in out)) out[name] = value;
  }
  return out;
}

/** An item's identifiers as editable rows (always at least one empty row to type into). */
export function identifierRows(identifiers: Record<string, unknown> | undefined): IdentifierRow[] {
  const rows = Object.entries(identifiers ?? {}).map(([name, value]) => ({ name, value: String(value ?? "") }));
  return rows.length > 0 ? rows : [{ name: "", value: "" }];
}

/** The identifiers of an item as one short line ("plate: KAA 123B · colour: red"). */
export const identifierText = (identifiers: Record<string, unknown>): string =>
  Object.entries(identifiers).map(([k, v]) => `${k}: ${String(v)}`).join(" · ");

/** Kinds of item offered as suggestions; anything else may be typed. */
export const ITEM_KINDS = ["vehicle", "phone", "appliance", "garment", "property", "other"] as const;
