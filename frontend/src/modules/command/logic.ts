/** Pure rules for the Command Center: how a figure moved, how figures are grouped, and how a brief's text is laid out. */
import type { Schemas } from "@/sdk";

export type Figure = Schemas["FigureOut"];
export type Direction = "up" | "down" | "flat" | "none";
export type Tone = "ok" | "bad" | "neutral";

export interface Change {
  direction: Direction;
  /** Percent against the day before; null when there is no day before or it was zero. */
  percent: number | null;
  /** Green when the move is good for the business, red when bad, neutral when it does not matter or nothing moved. */
  tone: Tone;
}

/** How today's value moved against yesterday's, coloured by whether higher is better. */
export function changeOf(value: string, previous: string | null, higherIsBetter: boolean | null): Change {
  const v = Number(value);
  if (previous === null || previous === "" || !Number.isFinite(v) || !Number.isFinite(Number(previous))) return { direction: "none", percent: null, tone: "neutral" };
  const p = Number(previous);
  const percent = p === 0 ? null : ((v - p) / Math.abs(p)) * 100;
  const flat = v === p || (percent !== null && Math.abs(percent) < 0.5);
  if (flat) return { direction: "flat", percent, tone: "neutral" };
  const direction: Direction = v > p ? "up" : "down";
  if (higherIsBetter === null) return { direction, percent, tone: "neutral" };
  return { direction, percent, tone: (direction === "up") === higherIsBetter ? "ok" : "bad" };
}

export interface FigureGroups {
  company: Figure[];
  branches: { id: string; name: string; figures: Figure[] }[];
}

/** Company-wide figures first, then one group per branch (by name). The server's order within a group is kept. */
export function groupFigures(figures: readonly Figure[]): FigureGroups {
  const company: Figure[] = [];
  const byBranch = new Map<string, { id: string; name: string; figures: Figure[] }>();
  for (const f of figures) {
    if (!f.branch_id) { company.push(f); continue; }
    const group = byBranch.get(f.branch_id) ?? { id: f.branch_id, name: f.branch_name ?? "", figures: [] };
    group.figures.push(f);
    byBranch.set(f.branch_id, group);
  }
  return { company, branches: [...byBranch.values()].sort((a, b) => a.name.localeCompare(b.name)) };
}

const AREA_ORDER = ["pos", "finance", "payments", "inventory", "purchasing", "crm", "people"] as const;

/** The area a figure belongs to: the unit that supplied it, which is the start of its metric code ("pos.sales_total"). */
export function areaOf(metric: string): string {
  return metric.split(".")[0] ?? metric;
}

/** Figures split by area (sales, money, stock, ...) in a fixed, sensible order; areas from future units come last. */
export function byArea(figures: readonly Figure[]): { area: string; figures: Figure[] }[] {
  const groups = new Map<string, Figure[]>();
  for (const f of figures) groups.set(areaOf(f.metric), [...(groups.get(areaOf(f.metric)) ?? []), f]);
  const rank = (a: string) => { const i = (AREA_ORDER as readonly string[]).indexOf(a); return i < 0 ? AREA_ORDER.length : i; };
  return [...groups.entries()].sort((a, b) => rank(a[0]) - rank(b[0]) || a[0].localeCompare(b[0])).map(([area, list]) => ({ area, figures: list }));
}

/** The first company-wide money figure: the "key figure" of the day. */
export function keyFigure(figures: readonly Figure[]): Figure | undefined {
  return figures.find((f) => !f.branch_id && f.kind === "money");
}

export const SEVERITY_ORDER = ["critical", "high", "medium", "low", "info"] as const;

/** Severity counts as an ordered list, most serious first; unknown severities from future checks come last. */
export function severityCounts(bySeverity: Record<string, number>): { severity: string; count: number }[] {
  const rank = (s: string) => { const i = (SEVERITY_ORDER as readonly string[]).indexOf(s); return i < 0 ? SEVERITY_ORDER.length : i; };
  return Object.entries(bySeverity).filter(([, n]) => n > 0).sort((a, b) => rank(a[0]) - rank(b[0])).map(([severity, count]) => ({ severity, count }));
}

/** "07:30:00" from the API to "07:30" for a time input. */
export const toTimeInput = (time: string): string => time.slice(0, 5);

export interface BriefSection {
  heading: string | null;
  items: { kind: "bullet" | "numbered" | "text"; text: string }[];
}
export interface BriefLayout {
  title: string;
  sections: BriefSection[];
}

/** Lays out a brief's plain text for reading: a title, then sections with a heading and bullet or numbered lines. */
export function layoutBrief(body: string): BriefLayout {
  const blocks = body.split(/\n\s*\n/).map((b) => b.split("\n").map((l) => l.trimEnd()).filter(Boolean)).filter((b) => b.length > 0);
  const title = blocks.shift()?.join(" ") ?? "";
  const itemOf = (line: string): BriefSection["items"][number] => {
    if (line.startsWith("- ")) return { kind: "bullet", text: line.slice(2) };
    const numbered = /^\d+\.\s+(.*)$/.exec(line);
    return numbered ? { kind: "numbered", text: numbered[1] } : { kind: "text", text: line };
  };
  const sections = blocks.map((lines): BriefSection => {
    const [first, ...rest] = lines;
    const firstIsItem = first.startsWith("- ") || /^\d+\.\s/.test(first);
    if (rest.length === 0 || firstIsItem) return { heading: null, items: lines.map(itemOf) };
    return { heading: first, items: rest.map(itemOf) };
  });
  return { title, sections };
}
